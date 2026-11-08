import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import Settings, get_settings
from .analytics import Analytics, ClickHouse
from .db import Business, Call, Database, MenuItem, Order, Payout, ProviderEvent, Refund, Staff, SupportCase, WebhookEvent
from .paypal.client import PayPalClient, PayPalError
from .policy import evaluate_payout, evaluate_refund
from .agents.runtime import crew_split
from .paypal.payments import PaymentRequest, build_payment_chain
from .providers.chain import AllProvidersFailed, FailoverEvent
from .providers.events import EventBus
from .providers.llm import ChatMessage, build_llm_chain
from .providers.voice import build_voice_chains
from .storage import ObjectStore
from .workflows import FlowEngine, FlowTimings, Ops

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("callpay")

FAILOVERS = Counter("callpay_failovers_total", "Provider failovers", ["layer", "from_provider"])
ORDERS = Counter("callpay_orders_total", "Orders by status", ["status"])
PAYOUTS = Counter("callpay_payouts_total", "Payouts by status", ["status"])


class State:
    settings: Settings
    http: httpx.AsyncClient
    db: Database
    bus: EventBus
    paypal: PayPalClient
    llm: object
    payments: object
    voice: dict
    flows: FlowEngine
    analytics: Analytics
    store: ObjectStore


state = State()


_background: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    """Fire-and-forget task that is still awaited on shutdown (never cut off mid-write)."""
    t = asyncio.get_running_loop().create_task(coro)
    _background.add(t)
    t.add_done_callback(_background.discard)
    return t


def _on_failover(ev: FailoverEvent) -> None:
    FAILOVERS.labels(ev.layer, ev.from_provider).inc()
    _spawn(_record_failover(ev))


async def _record_failover(ev: FailoverEvent) -> None:
    await state.bus.publish("provider.failover", ev.__dict__)
    async with state.db.session() as s:
        s.add(ProviderEvent(layer=ev.layer, from_provider=ev.from_provider, to_provider=ev.to_provider, reason=ev.reason[:500]))
        await s.commit()


async def _warm_llm() -> None:
    """Load the local model into GPU memory at startup so the first caller doesn't wait for it."""
    for p in state.llm.providers:
        if p.name.startswith("ollama") and p.configured():
            try:
                await p.complete("Reply with OK.", [ChatMessage("user", "ping")], 5)
                log.info("warmed %s", p.name)
                return
            except Exception as e:  # noqa: BLE001
                log.info("warm-up of %s failed: %s", p.name, e)


async def _seed() -> None:
    async with state.db.session() as s:
        biz = (await s.execute(select(Business).limit(1))).scalar_one_or_none()
        if not biz:
            biz = Business(name="Rosa's Taco Truck", currency="USD", phone="+15550100")
            s.add(biz)
            await s.flush()
            for name, price in [("Carne asada taco", "3.50"), ("Al pastor taco", "3.25"), ("Veggie burrito", "9.00"), ("Horchata", "2.75")]:
                s.add(MenuItem(business_id=biz.id, name=name, price=Decimal(price)))
        if not (await s.execute(select(Staff).limit(1))).first():
            emails = [e.strip() for e in state.settings.crew_emails.split(",") if e.strip()]
            emails += ["crew1@example.com", "crew2@example.com"][len(emails):]
            for (name, role), email in zip([("Rosa (cook)", "cook"), ("Miguel (cashier)", "cashier")], emails):
                s.add(Staff(business_id=biz.id, name=name, role=role, paypal_email=email))
        await s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = state.settings = get_settings()
    state.http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
    state.db = Database(s.database_url, s.sqlite_fallback_url)
    await state.db.connect()
    state.bus = EventBus(s.kafka_bootstrap)
    await state.bus.start()
    state.paypal = PayPalClient(s, state.http)
    state.llm = build_llm_chain(s, state.http, _on_failover)
    state.payments = build_payment_chain(state.paypal, s.app_url, _on_failover)
    state.voice = build_voice_chains(s, state.http, _on_failover)
    ch = ClickHouse(s.clickhouse_url, s.clickhouse_user, s.clickhouse_password, state.http)
    state.analytics = Analytics(ch, state.db, state.llm)
    state.analytics.kafka_feeds_clickhouse = await ch.start(s.kafka_bootstrap)
    state.bus.hooks.append(state.analytics.record)
    state.flows = FlowEngine(
        s.temporal_address, s.temporal_task_queue,
        Ops(status=_op_status, fulfil=_op_fulfil, ready=_op_ready, crew_payout=_op_crew_payout, remind=_op_remind, expire=_op_expire),
        FlowTimings(s.payment_timeout_s, s.reminder_wait_s, s.fulfil_seconds),
    )
    await state.flows.start()
    state.store = ObjectStore(s.s3_url, s.s3_bucket, s.local_storage_dir, state.http)
    await state.store.start()
    await _seed()
    _spawn(_warm_llm())
    yield
    await state.flows.stop()
    if _background:
        await asyncio.wait(list(_background), timeout=5)
    await state.bus.stop()
    await state.http.aclose()
    await state.db.close()


app = FastAPI(title="CallPay API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------- health & providers ----------------
@app.get("/health")
async def health():
    return {
        "ok": True,
        "database": state.db.backend,
        "event_bus": state.bus.backend,
        "paypal_configured": state.paypal.configured(),
        "workflows": state.flows.backend,
        "analytics": state.analytics.backend,
        "object_storage": state.store.backend,
    }


@app.get("/providers")
async def providers():
    return {
        "llm": state.llm.status(), "payments": state.payments.status(),
        **{k: c.status() for k, c in state.voice.items()},
        "database": state.db.backend, "event_bus": state.bus.backend,
        "workflows": state.flows.backend, "analytics": state.analytics.backend, "object_storage": state.store.backend,
    }


def _chain(layer: str):
    chains = {"llm": state.llm, "payments": state.payments, **state.voice}
    if layer not in chains:
        raise HTTPException(404, "unknown layer")
    return chains[layer]


@app.post("/providers/{layer}/{name}/kill")
async def kill_provider(layer: str, name: str):
    """Demo kill switch: force a provider offline to show failover."""
    chain = _chain(layer)
    if name not in chain.breakers:
        raise HTTPException(404, "unknown provider")
    chain.kill(name)
    await state.bus.publish("provider.health", {"layer": layer, "provider": name, "state": "open"})
    return chain.status()


@app.post("/providers/{layer}/{name}/revive")
async def revive_provider(layer: str, name: str):
    chain = _chain(layer)
    if name not in chain.breakers:
        raise HTTPException(404, "unknown provider")
    chain.revive(name)
    await state.bus.publish("provider.health", {"layer": layer, "provider": name, "state": "closed"})
    return chain.status()


class LLMTest(BaseModel):
    prompt: str = "Say hello as a friendly taco truck phone assistant, in one sentence."


@app.post("/llm/test")
async def llm_test(body: LLMTest):
    try:
        text, used = await state.llm.call(
            lambda p: p.complete("You are CallPay, a phone ordering assistant.", [ChatMessage("user", body.prompt)], 200)
        )
    except AllProvidersFailed as e:
        raise HTTPException(503, {"error": "all LLM providers failed", "details": e.errors})
    return {"provider": used, "text": text}


# ---------------- businesses & orders ----------------
@app.get("/businesses")
async def businesses():
    async with state.db.session() as s:
        rows = (await s.execute(select(Business))).scalars().all()
        return [
            {"id": b.id, "name": b.name, "currency": b.currency, "menu": [{"id": m.id, "name": m.name, "price": str(m.price)} for m in b.menu]}
            for b in rows
        ]


class OrderLine(BaseModel):
    menu_item_id: str
    quantity: int = Field(ge=1, le=50)


class CreateOrder(BaseModel):
    business_id: str
    customer_phone: str | None = None
    lines: list[OrderLine] = Field(min_length=1, max_length=30)
    call_id: str | None = None


def _order_json(o: Order) -> dict:
    return {
        "id": o.id, "business_id": o.business_id, "status": o.status, "total": str(o.total), "currency": o.currency,
        "items": o.items, "payment_method": o.payment_method, "paypal_ref": o.paypal_ref, "pay_link": o.pay_link,
        "created_at": o.created_at.isoformat() if o.created_at else None, "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        "call_id": o.call_id, "capture_id": o.capture_id, "dispute": o.dispute, "customer_phone": o.customer_phone,
    }


@app.post("/orders")
async def create_order(body: CreateOrder):
    """Prices always come from the menu in the database, never from the AI."""
    async with state.db.session() as s:
        biz = await s.get(Business, body.business_id)
        if not biz:
            raise HTTPException(404, "business not found")
        menu = {m.id: m for m in biz.menu}
        items = []
        for line in body.lines:
            m = menu.get(line.menu_item_id)
            if not m:
                raise HTTPException(400, f"unknown menu item {line.menu_item_id}")
            items.append({"name": m.name, "quantity": line.quantity, "unit_amount": str(m.price)})
        total = sum(Decimal(i["unit_amount"]) * i["quantity"] for i in items)
        order = Order(business_id=biz.id, customer_phone=body.customer_phone, items=items, total=total, currency=biz.currency, call_id=body.call_id)
        s.add(order)
        await s.commit()

        try:
            link, method = await state.payments.call(
                lambda p: p.create(PaymentRequest(order.id, total, biz.currency, f"{biz.name} order {order.id[:8]}", items))
            )
        except AllProvidersFailed as e:
            order.status = "failed"
            await s.commit()
            ORDERS.labels("failed").inc()
            raise HTTPException(503, {"error": "could not create PayPal payment", "order_id": order.id, "details": e.errors})

        order.status, order.payment_method, order.paypal_ref, order.pay_link = "link_sent", method, link.paypal_ref, link.url
        await s.commit()
        ORDERS.labels("link_sent").inc()
        await state.bus.publish("payment.link_sent", {"order_id": order.id, "method": method, "total": str(total), "call_id": order.call_id})
        await state.bus.publish("order.created", {"order_id": order.id, "total": str(total), "call_id": order.call_id})
        out = _order_json(order)
    out["workflow"] = await state.flows.start_order(order.id)
    return out


@app.get("/orders")
async def list_orders():
    async with state.db.session() as s:
        rows = (await s.execute(select(Order).order_by(Order.created_at.desc()).limit(200))).scalars().all()
        return [_order_json(o) for o in rows]


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        if not o:
            raise HTTPException(404, "order not found")
        return _order_json(o)


async def _mark_paid(paypal_ref: str | None = None, order_id: str | None = None, capture_id: str | None = None) -> Order | None:
    async with state.db.session() as s:
        o = await s.get(Order, order_id) if order_id else None
        if not o and paypal_ref:
            o = (await s.execute(select(Order).where(Order.paypal_ref == paypal_ref))).scalar_one_or_none()
        if not o:
            return None
        if capture_id and not o.capture_id:
            o.capture_id = capture_id
            await s.commit()
        if o.status not in ("created", "link_sent", "expired", "failed"):
            return o
        o.status, o.paid_at = "paid", datetime.now(timezone.utc)
        await s.commit()
        ORDERS.labels("paid").inc()
        await state.bus.publish("payment.completed", {"order_id": o.id, "total": str(o.total), "call_id": o.call_id})
    await state.flows.signal_paid(o.id)
    return o


@app.get("/paypal/return", response_class=HTMLResponse)
async def paypal_return(ref: str, token: str):
    """Buyer approved on PayPal -> capture the order, then send them back to their call."""
    async with state.db.session() as s:
        o = await s.get(Order, ref)
        if not o or o.paypal_ref != token:
            raise HTTPException(400, "order mismatch")
        already_paid = o.status in ("paid", "preparing", "ready")
        call_id = o.call_id
    if not already_paid:
        try:
            capture = await state.paypal.capture_order(token, ref)
        except PayPalError as e:  # e.g. ORDER_ALREADY_CAPTURED on a page refresh
            if "ORDER_ALREADY_CAPTURED" not in str(e.body):
                return HTMLResponse(_return_page("We couldn't complete the payment", "Please try the link again.", None), 502)
            capture = {"status": "COMPLETED"}
        if capture.get("status") != "COMPLETED":
            return _return_page(f"Payment status: {capture.get('status')}", "Please try the link again.", None)
        caps = [c for pu in capture.get("purchase_units", []) for c in pu.get("payments", {}).get("captures", [])]
        await _mark_paid(order_id=ref, capture_id=caps[0]["id"] if caps else None)
    return _return_page("Payment received, thank you!", "Taking you back to your call...", call_id)


def _web_url() -> str:
    """Public dashboard URL: APP_URL without its /api suffix (Kong/Caddy serve both)."""
    url = state.settings.app_url.rstrip("/")
    return url[: -len("/api")] if url.endswith("/api") else "http://localhost:8090"


def _return_page(title: str, body: str, call_id: str | None) -> str:
    """If PayPal opened in a new tab, close it (the call tab hears the confirmation).
    If it replaced the call tab, go back to the call page, which resumes the call."""
    back = f"{_web_url()}/call?resume={call_id}" if call_id else f"{_web_url()}/"
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CallPay</title><body style="font-family:system-ui;max-width:28rem;margin:4rem auto;padding:0 1rem;text-align:center">
<h1 style="font-size:1.4rem">{title}</h1><p>{body}</p><p><a href="{back}">Return to your call</a></p>
<script>setTimeout(function(){{ if (window.opener) {{ window.close(); }} location.replace({json.dumps(back)}); }}, 1500);</script>"""


@app.get("/paypal/cancel", response_class=HTMLResponse)
async def paypal_cancel(ref: str):
    return "<h1>Payment cancelled</h1>"


@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    event = await request.json()
    if not await state.paypal.verify_webhook(dict(request.headers), event):
        raise HTTPException(400, "invalid webhook signature")
    async with state.db.session() as s:
        if await s.get(WebhookEvent, event["id"]):
            return {"ok": True, "duplicate": True}
        s.add(WebhookEvent(id=event["id"], event_type=event.get("event_type", ""), payload=event))
        await s.commit()
    etype, res = event.get("event_type"), event.get("resource", {})
    if etype == "PAYMENT.CAPTURE.COMPLETED":
        order_id = res.get("custom_id")
        related = res.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        await _mark_paid(paypal_ref=related, order_id=order_id, capture_id=res.get("id"))
    elif etype in ("INVOICING.INVOICE.PAID",):
        await _mark_paid(paypal_ref=res.get("invoice", {}).get("id") or res.get("id"))
    elif etype in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        await state.bus.publish("payment.refunded", {"capture_id": res.get("id"), "event": etype})
    elif etype and etype.startswith("CUSTOMER.DISPUTE."):
        await _dispute_webhook(etype, res)
    elif etype and (etype.startswith("PAYMENT.PAYOUTSBATCH.") or etype.startswith("PAYMENT.PAYOUTS-ITEM.")):
        await _payout_webhook(etype, res)
    await state.bus.publish("paypal.webhook", {"event_type": etype, "id": event["id"]})
    return {"ok": True}


# ---------------- staff & payouts ----------------
class CreateStaff(BaseModel):
    business_id: str
    name: str = Field(min_length=1, max_length=200)
    paypal_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    role: str = Field(default="crew", max_length=40)


def _staff_json(m: Staff) -> dict:
    return {"id": m.id, "business_id": m.business_id, "name": m.name, "paypal_email": m.paypal_email, "role": m.role, "active": m.active}


@app.get("/staff")
async def list_staff(business_id: str | None = None):
    async with state.db.session() as s:
        q = select(Staff).where(Staff.active.is_(True))
        if business_id:
            q = q.where(Staff.business_id == business_id)
        return [_staff_json(m) for m in (await s.execute(q)).scalars().all()]


@app.post("/staff")
async def create_staff(body: CreateStaff):
    async with state.db.session() as s:
        if not await s.get(Business, body.business_id):
            raise HTTPException(404, "business not found")
        m = Staff(**body.model_dump())
        s.add(m)
        await s.commit()
        return _staff_json(m)


class PayoutLine(BaseModel):
    staff_id: str
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str = Field(default="", max_length=500)


class CreatePayout(BaseModel):
    business_id: str
    lines: list[PayoutLine] = Field(min_length=1, max_length=50)
    memo: str = Field(default="Crew payout", max_length=500)


def _iso(d):
    return d.isoformat() if d else None


def _payout_json(p: Payout) -> dict:
    return {
        "id": p.id, "business_id": p.business_id, "status": p.status, "total": f"{p.total:.2f}", "currency": p.currency,
        "items": p.items, "memo": p.memo, "policy": p.policy, "paypal_batch_id": p.paypal_batch_id, "error": p.error,
        "decided_by": p.decided_by, "created_at": _iso(p.created_at), "decided_at": _iso(p.decided_at), "sent_at": _iso(p.sent_at),
    }


async def _send_payout(s, p: Payout) -> None:
    """Execute via PayPal Payouts. Idempotent: sender_batch_id and PayPal-Request-Id derive from the payout id.
    Fallback: on failure the payout goes back to the approval queue instead of being lost."""
    try:
        res = await state.paypal.create_payout(
            batch_id=p.id, currency=p.currency, subject=p.memo,
            items=[{"email": i["email"], "amount": i["amount"], "item_id": i["item_id"], "note": i.get("note") or p.memo} for i in p.items],
        )
    except (PayPalError, httpx.HTTPError) as e:
        p.status, p.error = "pending_approval", f"PayPal Payouts failed, queued for retry/approval: {e}"[:1000]
        await s.commit()
        PAYOUTS.labels("failed").inc()
        await state.bus.publish("payout.failed", {"payout_id": p.id, "error": p.error})
        return
    p.paypal_batch_id = res.get("batch_header", {}).get("payout_batch_id")
    p.status, p.error, p.sent_at = "sent", None, datetime.now(timezone.utc)
    await s.commit()
    PAYOUTS.labels("sent").inc()
    await state.bus.publish("payout.sent", {"payout_id": p.id, "paypal_batch_id": p.paypal_batch_id, "total": f"{p.total:.2f}"})


@app.post("/payouts")
async def create_payout(body: CreatePayout):
    """Propose a crew payout. The policy engine decides: auto-send, owner approval, or deny."""
    st = state.settings
    async with state.db.session() as s:
        biz = await s.get(Business, body.business_id)
        if not biz:
            raise HTTPException(404, "business not found")
        q = select(Staff).where(Staff.business_id == biz.id, Staff.active.is_(True))
        staff = {m.id: m for m in (await s.execute(q)).scalars()}
        items = []
        for line in body.lines:
            m = staff.get(line.staff_id)
            if not m:
                raise HTTPException(400, f"unknown staff member {line.staff_id}")
            items.append({"staff_id": m.id, "name": m.name, "email": m.paypal_email, "amount": f"{line.amount:.2f}", "note": line.note})
        decision = evaluate_payout(
            items, auto_limit=Decimal(str(st.payout_auto_approve_limit)),
            max_total=Decimal(str(st.payout_max_total)), max_item=Decimal(str(st.payout_max_item)),
        )
        p = Payout(
            id=uuid.uuid4().hex, business_id=biz.id, currency=biz.currency, memo=body.memo, policy=decision.as_dict(),
            total=sum(Decimal(i["amount"]) for i in items),
            status={"deny": "rejected", "approval": "pending_approval", "auto": "approved"}[decision.decision],
        )
        p.items = [{"item_id": f"{p.id[:24]}-{n}", **i} for n, i in enumerate(items)]
        if decision.decision != "approval":
            p.decided_by, p.decided_at = "policy", datetime.now(timezone.utc)
        s.add(p)
        await s.commit()
        PAYOUTS.labels(p.status).inc()
        await state.bus.publish("payout.requested", {"payout_id": p.id, "total": f"{p.total:.2f}", "decision": decision.decision})
        if p.status == "approved":
            await _send_payout(s, p)
        return _payout_json(p)


@app.get("/payouts")
async def list_payouts(status: str | None = None):
    async with state.db.session() as s:
        q = select(Payout).order_by(Payout.created_at.desc()).limit(200)
        if status:
            q = q.where(Payout.status == status)
        return [_payout_json(p) for p in (await s.execute(q)).scalars().all()]


@app.get("/approvals")
async def approval_queue():
    """Everything waiting for the owner (payouts today; refunds and disputes later)."""
    return {"payouts": await list_payouts(status="pending_approval")}


class Decide(BaseModel):
    by: str = Field(default="owner", max_length=100)


async def _decide(payout_id: str, approve: bool, by: str) -> dict:
    async with state.db.session() as s:
        p = await s.get(Payout, payout_id)
        if not p:
            raise HTTPException(404, "payout not found")
        if p.status != "pending_approval":
            raise HTTPException(409, f"payout is {p.status}")
        p.status = "approved" if approve else "rejected"
        p.decided_by, p.decided_at = by, datetime.now(timezone.utc)
        await s.commit()
        if approve:
            await _send_payout(s, p)
        else:
            PAYOUTS.labels("rejected").inc()
            await state.bus.publish("payout.rejected", {"payout_id": p.id})
        return _payout_json(p)


@app.post("/payouts/{payout_id}/approve")
async def approve_payout(payout_id: str, body: Decide | None = None):
    return await _decide(payout_id, True, (body or Decide()).by)


@app.post("/payouts/{payout_id}/reject")
async def reject_payout(payout_id: str, body: Decide | None = None):
    return await _decide(payout_id, False, (body or Decide()).by)


async def _payout_webhook(etype: str, res: dict) -> None:
    header = res.get("batch_header", {})
    batch_id = header.get("payout_batch_id") or res.get("payout_batch_id")
    sender_id = header.get("sender_batch_header", {}).get("sender_batch_id")
    async with state.db.session() as s:
        p = await s.get(Payout, sender_id) if sender_id else None
        if not p and batch_id:
            p = (await s.execute(select(Payout).where(Payout.paypal_batch_id == batch_id))).scalar_one_or_none()
        if not p:
            return
        if etype == "PAYMENT.PAYOUTSBATCH.SUCCESS":
            p.status = "completed"
        elif etype == "PAYMENT.PAYOUTSBATCH.DENIED":
            p.status, p.error = "failed", "PayPal denied the payout batch"
        elif etype.startswith("PAYMENT.PAYOUTS-ITEM."):
            item_id = res.get("payout_item", {}).get("sender_item_id")
            p.items = [{**i, "paypal_status": res.get("transaction_status")} if i["item_id"] == item_id else i for i in p.items]
        await s.commit()
        await state.bus.publish("payout.updated", {"payout_id": p.id, "status": p.status, "event": etype})


# ---------------- workflow steps (called by the in-process runner and by Temporal via /internal) ----------------
async def _set_order_status(order_id: str, frm: tuple[str, ...], to: str, topic: str) -> Order | None:
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        if not o or o.status not in frm:
            return o
        o.status = to
        await s.commit()
        ORDERS.labels(to).inc()
        await state.bus.publish(topic, {"order_id": o.id, "total": str(o.total), "call_id": o.call_id, "items": o.items})
        return o


async def _op_status(order_id: str) -> str:
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        return o.status if o else "missing"


async def _op_fulfil(order_id: str) -> None:
    """Kitchen ticket: the dashboard's kitchen view shows every 'preparing' order."""
    await _set_order_status(order_id, ("paid",), "preparing", "order.preparing")


async def _op_ready(order_id: str) -> None:
    o = await _set_order_status(order_id, ("preparing",), "ready", "order.ready")
    if o and o.customer_phone:
        await _send_sms(o.customer_phone, "Your order is ready for pickup. Thanks for ordering with CallPay!")


async def _op_crew_payout(order_id: str) -> None:
    """Payouts sub-agent: crew_share_pct of the order goes to the crew, through the policy engine."""
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        if not o:
            return
        staff = [{"id": m.id} for m in (await s.execute(
            select(Staff).where(Staff.business_id == o.business_id, Staff.active.is_(True)))).scalars()]
    lines = crew_split(o.total, staff, Decimal(str(state.settings.crew_share_pct)))
    if lines:
        await create_payout(CreatePayout(
            business_id=o.business_id, memo=f"Crew share for order {o.id[:8]}",
            lines=[PayoutLine(staff_id=line["staff_id"], amount=line["amount"]) for line in lines]))


async def _op_remind(order_id: str) -> None:
    """Missed-call recovery: the caller hung up without paying -> text them the link again."""
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        if not o or o.status != "link_sent":
            return
        call = await s.get(Call, o.call_id) if o.call_id else None
        if call and call.status in ("ended", "abandoned"):
            call.status = "recovered"
            await s.commit()
    channel = "none"
    if o.customer_phone:
        channel = await _send_sms(o.customer_phone, f"Still hungry? Your order (${o.total:.2f}) is saved. Pay here: {o.pay_link}")
    # only a text that actually went out counts as a recovery attempt
    topic = "recovery.sent" if channel == "sms" else "recovery.skipped"
    await state.bus.publish(topic, {"order_id": o.id, "call_id": o.call_id, "channel": channel, "total": str(o.total)})


async def _op_expire(order_id: str) -> None:
    await _set_order_status(order_id, ("link_sent", "created"), "expired", "order.expired")


async def _send_sms(to: str, body: str) -> str:
    """SMS chain: Twilio -> Telnyx. Returns the channel used, or 'screen' if no SMS provider works."""
    try:
        _, used = await state.voice["sms"].call(lambda p: p.send(to, body))
        await state.bus.publish("sms.sent", {"provider": used})
        return "sms"
    except AllProvidersFailed:
        return "screen"


STEPS = {"fulfil": _op_fulfil, "ready": _op_ready, "crew_payout": _op_crew_payout, "remind": _op_remind, "expire": _op_expire}


@app.post("/internal/orders/{order_id}/{step}", include_in_schema=False)
async def internal_step(order_id: str, step: str, request: Request):
    # Only reachable inside the cluster: Kong/Caddy don't route /internal for outside callers.
    if request.headers.get("x-forwarded-for"):
        raise HTTPException(403, "internal only")
    if step not in STEPS:
        raise HTTPException(404, "unknown step")
    await STEPS[step](order_id)
    return {"ok": True}


@app.get("/kitchen")
async def kitchen():
    async with state.db.session() as s:
        q = select(Order).where(Order.status.in_(("paid", "preparing", "ready"))).order_by(Order.paid_at.desc()).limit(50)
        return [_order_json(o) for o in (await s.execute(q)).scalars()]


# ---------------- refunds & disputes (Support sub-agent + owner approval) ----------------
class CreateRefund(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    reason: str = Field(default="Customer request", max_length=500)


def _refund_json(r: Refund) -> dict:
    return {"id": r.id, "order_id": r.order_id, "amount": f"{r.amount:.2f}", "currency": r.currency, "reason": r.reason,
            "status": r.status, "policy": r.policy, "paypal_refund_id": r.paypal_refund_id, "error": r.error,
            "decided_by": r.decided_by, "created_at": _iso(r.created_at)}


async def _send_refund(s, r: Refund, o: Order) -> None:
    try:
        res = await state.paypal.refund_capture(o.capture_id, amount=r.amount, currency=r.currency, refund_id=r.id, note=r.reason)
    except (PayPalError, httpx.HTTPError) as e:
        r.status, r.error = "pending_approval", f"PayPal refund failed, queued: {e}"[:1000]
        await s.commit()
        return
    r.status, r.paypal_refund_id, r.error = "sent", res.get("id"), None
    await s.commit()
    await state.bus.publish("payment.refunded", {"order_id": o.id, "refund_id": r.id, "total": f"-{r.amount:.2f}"})


@app.post("/orders/{order_id}/refund")
async def refund_order(order_id: str, body: CreateRefund):
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        if not o:
            raise HTTPException(404, "order not found")
        if not o.capture_id:
            raise HTTPException(409, "order has no captured payment to refund")
        prior = (await s.execute(select(Refund).where(Refund.order_id == o.id, Refund.status.in_(("sent", "approved", "pending_approval"))))).scalars()
        already = sum((x.amount for x in prior), Decimal("0"))
        amount = body.amount or (o.total - already)
        d = evaluate_refund(amount, o.total, already, auto_limit=Decimal(str(state.settings.refund_auto_limit)))
        r = Refund(order_id=o.id, amount=amount, currency=o.currency, reason=body.reason, policy=d.as_dict(),
                   status={"deny": "rejected", "approval": "pending_approval", "auto": "approved"}[d.decision],
                   decided_by="policy" if d.decision != "approval" else None)
        s.add(r)
        await s.commit()
        if r.status == "approved":
            await _send_refund(s, r, o)
        return _refund_json(r)


@app.get("/refunds")
async def list_refunds(status: str | None = None):
    async with state.db.session() as s:
        q = select(Refund).order_by(Refund.created_at.desc()).limit(200)
        if status:
            q = q.where(Refund.status == status)
        return [_refund_json(r) for r in (await s.execute(q)).scalars()]


@app.post("/refunds/{refund_id}/{decision}")
async def decide_refund(refund_id: str, decision: str, body: Decide | None = None):
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "unknown decision")
    async with state.db.session() as s:
        r = await s.get(Refund, refund_id)
        if not r:
            raise HTTPException(404, "refund not found")
        if r.status != "pending_approval":
            raise HTTPException(409, f"refund is {r.status}")
        r.decided_by = (body or Decide()).by
        r.status = "approved" if decision == "approve" else "rejected"
        await s.commit()
        if r.status == "approved":
            await _send_refund(s, r, await s.get(Order, r.order_id))
        return _refund_json(r)


async def _draft_dispute_evidence(o: Order) -> str:
    """Support sub-agent: summarise the call transcript as dispute evidence (LLM, template fallback)."""
    lines = []
    async with state.db.session() as s:
        call = await s.get(Call, o.call_id) if o.call_id else None
    if call:
        lines = [f"{t['role']}: {t['text']}" for t in call.transcript][-30:]
    facts = (f"Order {o.id} for ${o.total:.2f} placed by phone on {_iso(o.created_at)}; items: "
             + ", ".join(f"{i['quantity']} x {i['name']}" for i in o.items)
             + f". Paid via PayPal at {_iso(o.paid_at)}. Status: {o.status}.")
    if not lines:
        return facts
    try:
        text, _ = await asyncio.wait_for(state.llm.call(lambda p: p.complete(
            "Write a factual 4-sentence PayPal dispute evidence note for a merchant. Use only the facts and transcript given. No speculation.",
            [ChatMessage("user", facts + "\nTranscript:\n" + "\n".join(lines))], 300)), timeout=20)
        return f"{facts}\n\n{text.strip()}"[:2000]
    except Exception:  # noqa: BLE001
        return (facts + "\n\nCall transcript excerpt:\n" + "\n".join(lines[-10:]))[:2000]


async def _dispute_webhook(etype: str, res: dict) -> None:
    dispute_id = res.get("dispute_id")
    txns = res.get("disputed_transactions") or [{}]
    capture_id = txns[0].get("seller_transaction_id")
    custom = txns[0].get("custom")
    async with state.db.session() as s:
        o = await s.get(Order, custom) if custom else None
        if not o and capture_id:
            o = (await s.execute(select(Order).where(Order.capture_id == capture_id))).scalar_one_or_none()
        if not o:
            return
        d = dict(o.dispute or {})
        d.update(id=dispute_id, reason=res.get("reason"), status=res.get("status"), event=etype)
        if "draft_evidence" not in d:
            d["draft_evidence"] = await _draft_dispute_evidence(o)
        o.dispute = d
        await s.commit()
    await state.bus.publish("dispute.updated", {"order_id": o.id, "dispute_id": dispute_id, "status": d["status"]})


@app.post("/orders/{order_id}/dispute/submit")
async def submit_dispute_evidence(order_id: str):
    """Owner approved the drafted evidence -> send it to PayPal."""
    async with state.db.session() as s:
        o = await s.get(Order, order_id)
        if not o or not o.dispute:
            raise HTTPException(404, "no dispute on this order")
        try:
            await state.paypal.provide_dispute_evidence(o.dispute["id"], o.dispute["draft_evidence"])
        except PayPalError as e:
            raise HTTPException(502, f"PayPal rejected the evidence: {e}")
        o.dispute = {**o.dispute, "evidence_submitted": True}
        await s.commit()
        return _order_json(o)


@app.get("/support")
async def support_cases():
    async with state.db.session() as s:
        rows = (await s.execute(select(SupportCase).order_by(SupportCase.created_at.desc()).limit(100))).scalars()
        return [{"id": c.id, "call_id": c.call_id, "order_id": c.order_id, "text": c.text, "status": c.status,
                 "created_at": _iso(c.created_at)} for c in rows]


# ---------------- analytics & "ask your business" ----------------
class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=300)


@app.post("/analytics/ask")
async def analytics_ask(body: Ask):
    return await state.analytics.ask(body.question)


@app.get("/analytics/metric/{name}")
async def analytics_metric(name: str, window: str = "week"):
    try:
        return await state.analytics.metric(name, window)
    except ValueError:
        raise HTTPException(404, "unknown metric")


@app.get("/analytics/timeseries")
async def analytics_timeseries(minutes: int = 60):
    return await state.analytics.timeseries(max(5, min(minutes, 1440)))


@app.get("/analytics/summary")
async def analytics_summary(window: str = "today"):
    rev = await state.analytics.metric("revenue", window)
    calls = await state.analytics.metric("missed_calls", window)
    pay = await state.analytics.metric("payouts", window)
    return {**rev, **{k: v for k, v in calls.items() if k != "source"}, **{k: v for k, v in pay.items() if k != "source"},
            "window": window}


# ---------------- live events & metrics ----------------
@app.get("/events")
async def events(request: Request):
    q = state.bus.subscribe()

    async def gen():
        yield "retry: 3000\n: connected\n\n"  # flush headers immediately so proxies open the stream
        try:
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            state.bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Routers that need everything above (imported last on purpose).
from .routes_voice import router as voice_router  # noqa: E402

app.include_router(voice_router)
