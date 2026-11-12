"""Owner operations: menu editor, fraud guard + per-caller rate limits, owner alerts, PayPal reconciliation.

Money rules stay the same as everywhere else in CallPay:
- menu prices are typed by the owner and validated here; the AI never writes them;
- fraud flags only ever make the rules stricter (lower checkout cap, refunds need the owner);
- reconciliation is read-only against PayPal's Transaction Search API.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import main as core
from .db import Business, Call, FraudFlag, MenuItem, Order, OwnerAlert
from .paypal.client import PayPalError

log = logging.getLogger("callpay.ops")
router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- menu editor ----------------
class MenuItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, le=1000, max_digits=7, decimal_places=2)


class MenuItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    price: Decimal | None = Field(default=None, gt=0, le=1000, max_digits=7, decimal_places=2)


def _item_json(m: MenuItem) -> dict:
    return {"id": m.id, "business_id": m.business_id, "name": m.name, "price": f"{m.price:.2f}"}


async def _name_taken(s, business_id: str, name: str, except_id: str | None = None) -> bool:
    rows = (await s.execute(select(MenuItem).where(MenuItem.business_id == business_id))).scalars()
    return any(m.name.strip().lower() == name.strip().lower() and m.id != except_id for m in rows)


@router.post("/businesses/{business_id}/menu")
async def add_menu_item(business_id: str, body: MenuItemIn):
    async with core.state.db.session() as s:
        if not await s.get(Business, business_id):
            raise HTTPException(404, "business not found")
        name = " ".join(body.name.split())
        if await _name_taken(s, business_id, name):
            raise HTTPException(409, f"'{name}' is already on the menu")
        m = MenuItem(business_id=business_id, name=name, price=body.price)
        s.add(m)
        await s.commit()
        out = _item_json(m)
    await core._audit("owner", "menu.item_added", "menu_item", out["id"], {"name": out["name"], "price": out["price"]})
    await core.state.bus.publish("menu.updated", {"business_id": business_id, "change": "added", "name": out["name"]})
    return out


@router.put("/menu/{item_id}")
async def update_menu_item(item_id: str, body: MenuItemPatch):
    async with core.state.db.session() as s:
        m = await s.get(MenuItem, item_id)
        if not m:
            raise HTTPException(404, "menu item not found")
        before = _item_json(m)
        if body.name is not None:
            name = " ".join(body.name.split())
            if await _name_taken(s, m.business_id, name, except_id=m.id):
                raise HTTPException(409, f"'{name}' is already on the menu")
            m.name = name
        if body.price is not None:
            m.price = body.price
        await s.commit()
        out = _item_json(m)
    if out != before:
        await core._audit("owner", "menu.item_changed", "menu_item", item_id,
                          {"from": {"name": before["name"], "price": before["price"]}, "to": {"name": out["name"], "price": out["price"]}})
        await core.state.bus.publish("menu.updated", {"business_id": out["business_id"], "change": "changed", "name": out["name"]})
    return out


@router.delete("/menu/{item_id}")
async def delete_menu_item(item_id: str):
    """Past orders keep their own copy of the item name and price, so removing an item never rewrites history."""
    async with core.state.db.session() as s:
        m = await s.get(MenuItem, item_id)
        if not m:
            raise HTTPException(404, "menu item not found")
        count = (await s.execute(select(func.count()).select_from(MenuItem).where(MenuItem.business_id == m.business_id))).scalar_one()
        if count <= 1:
            raise HTTPException(409, "the menu needs at least one item")
        gone = _item_json(m)
        await s.delete(m)
        await s.commit()
    await core._audit("owner", "menu.item_removed", "menu_item", item_id, {"name": gone["name"], "price": gone["price"]})
    await core.state.bus.publish("menu.updated", {"business_id": gone["business_id"], "change": "removed", "name": gone["name"]})
    return {"ok": True}


# ---------------- fraud guard + rate limits ----------------
def _flag_json(f: FraudFlag) -> dict:
    return {"id": f.id, "caller": f.caller, "reason": f.reason, "source": f.source, "active": f.active,
            "created_at": core._iso(f.created_at), "expires_at": core._iso(f.expires_at)}


async def active_flag(caller: str | None) -> dict | None:
    if not caller:
        return None
    async with core.state.db.session() as s:
        q = select(FraudFlag).where(FraudFlag.caller == caller, FraudFlag.active.is_(True), FraudFlag.expires_at > _now())
        f = (await s.execute(q.order_by(FraudFlag.created_at.desc()).limit(1))).scalar_one_or_none()
        return _flag_json(f) if f else None


async def flag_caller(caller: str, reason: str, source: str) -> dict:
    st = core.state.settings
    async with core.state.db.session() as s:
        f = FraudFlag(caller=caller, reason=reason[:300], source=source, expires_at=_now() + timedelta(minutes=st.fraud_flag_minutes))
        s.add(f)
        await s.commit()
        out = _flag_json(f)
    await core._audit(source, "fraud.flagged", "caller", caller, {"reason": out["reason"], "expires_at": out["expires_at"]})
    await core.state.bus.publish("fraud.flagged", {"caller": caller, "reason": out["reason"], "flag_id": out["id"]})
    return out


async def guard_new_call(caller: str | None) -> None:
    """Called before a call is created. Too many calls from one number: flag it, then refuse."""
    if not caller:
        return
    st = core.state.settings
    since = _now() - timedelta(minutes=st.fraud_window_minutes)
    async with core.state.db.session() as s:
        recent = (await s.execute(select(func.count()).select_from(Call).where(Call.caller == caller, Call.started_at >= since))).scalar_one()
    if recent >= st.rate_calls_per_window:
        raise HTTPException(429, {"code": "rate_limited", "say": "We've had a lot of calls from this number. Please try again in a few minutes."})
    if recent + 1 >= st.fraud_calls_threshold and not await active_flag(caller):
        await flag_caller(caller, f"{recent + 1} calls in {st.fraud_window_minutes} minutes", "rule")


async def guard_checkout(caller: str | None, payable_total: Decimal) -> None:
    """Called by create_order before PayPal is contacted."""
    if not caller:
        return
    st = core.state.settings
    async with core.state.db.session() as s:
        since = _now() - timedelta(hours=1)
        checkouts = (await s.execute(select(func.count()).select_from(Order).where(Order.customer_phone == caller, Order.created_at >= since))).scalar_one()
    if checkouts >= st.rate_checkouts_per_hour:
        raise HTTPException(429, {"code": "rate_limited", "say": "You've reached the limit of orders for now. Please try again later."})
    cap = Decimal(str(st.fraud_checkout_cap))
    if payable_total > cap and await active_flag(caller):
        raise HTTPException(403, {"code": "fraud_cap", "say": f"I can take orders up to ${cap:.2f} by phone right now. "
                                                              "Would you like to remove something, or order at the counter?"})


class ManualFlag(BaseModel):
    caller: str = Field(min_length=3, max_length=32)
    reason: str = Field(default="Flagged by the owner", max_length=300)


@router.get("/fraud/flags")
async def list_flags():
    async with core.state.db.session() as s:
        rows = (await s.execute(select(FraudFlag).order_by(FraudFlag.created_at.desc()).limit(100))).scalars().all()
        now = _now()
        out = []
        for f in rows:
            j = _flag_json(f)
            exp = f.expires_at if f.expires_at.tzinfo else f.expires_at.replace(tzinfo=timezone.utc)
            j["in_effect"] = bool(f.active and exp > now)
            out.append(j)
    st = core.state.settings
    return {"flags": out, "rules": {
        "flag_after_calls": st.fraud_calls_threshold, "window_minutes": st.fraud_window_minutes, "flag_minutes": st.fraud_flag_minutes,
        "checkout_cap": f"{st.fraud_checkout_cap:.2f}", "max_calls_per_window": st.rate_calls_per_window,
        "max_checkouts_per_hour": st.rate_checkouts_per_hour, "max_turns_per_call": st.rate_turns_per_call}}


@router.post("/fraud/flags")
async def create_flag(body: ManualFlag):
    return await flag_caller(body.caller.strip(), body.reason, "owner")


@router.post("/fraud/flags/{flag_id}/clear")
async def clear_flag(flag_id: str):
    async with core.state.db.session() as s:
        f = await s.get(FraudFlag, flag_id)
        if not f:
            raise HTTPException(404, "flag not found")
        f.active = False
        await s.commit()
        out = _flag_json(f)
    await core._audit("owner", "fraud.cleared", "caller", out["caller"], {"flag_id": flag_id})
    await core.state.bus.publish("fraud.cleared", {"caller": out["caller"], "flag_id": flag_id})
    return out


# ---------------- owner alerts ----------------
_last_alert: dict[str, float] = {}


def _alert_for(topic: str, p: dict) -> tuple[str, str, str | None] | None:
    """(kind, message, entity id) for events the owner should hear about, else None."""
    if topic == "payout.requested" and p.get("decision") == "approval":
        return "payout_approval", f"A crew payout of ${p.get('total')} needs your approval.", p.get("payout_id")
    if topic == "payout.failed":
        return "payout_failed", "A crew payout failed at PayPal and is waiting in your approval queue.", p.get("payout_id")
    if topic == "refund.requested" and p.get("status") == "pending_approval":
        return "refund_approval", f"A refund of ${p.get('amount')} needs your approval.", p.get("refund_id")
    if topic == "dispute.updated":
        return "dispute", f"PayPal dispute {p.get('dispute_id')} is now {p.get('status')}.", p.get("order_id")
    if topic == "fraud.flagged":
        return "fraud", f"Caller {p.get('caller')} was flagged: {p.get('reason')}.", p.get("flag_id")
    if topic == "order.created":
        try:
            if Decimal(str(p.get("total"))) >= Decimal(str(core.state.settings.owner_alert_order_total)):
                return "large_order", f"Large order: ${p.get('total')}.", p.get("order_id")
        except Exception:  # noqa: BLE001
            return None
    return None


async def alert_hook(topic: str, payload: dict, backend: str) -> None:
    """Event-bus hook. Never blocks the money flow: delivery runs in the background."""
    hit = _alert_for(topic, payload)
    if not hit:
        return
    kind, message, entity_id = hit
    now = time.monotonic()
    if now - _last_alert.get(kind, -1e9) < core.state.settings.owner_alert_cooldown_s:
        return
    _last_alert[kind] = now
    core._spawn(_deliver_alert(kind, message, entity_id))


async def _deliver_alert(kind: str, message: str, entity_id: str | None) -> None:
    channel = "screen"
    phone = core.state.settings.owner_phone
    if phone:
        channel = await core._send_sms(phone, f"CallPay: {message}")
    async with core.state.db.session() as s:
        s.add(OwnerAlert(kind=kind, message=message, channel=channel, entity_id=entity_id))
        await s.commit()
    await core.state.bus.publish("owner.alert", {"kind": kind, "message": message, "channel": channel})


@router.get("/alerts")
async def list_alerts(limit: int = 50):
    async with core.state.db.session() as s:
        rows = (await s.execute(select(OwnerAlert).order_by(OwnerAlert.created_at.desc()).limit(min(limit, 200)))).scalars()
        alerts = [{"id": a.id, "kind": a.kind, "message": a.message, "channel": a.channel, "entity_id": a.entity_id,
                   "created_at": core._iso(a.created_at)} for a in rows]
    st = core.state.settings
    sms_ready = any(p["configured"] for p in core.state.voice["sms"].status())
    return {"alerts": alerts, "delivery": "sms" if (st.owner_phone and sms_ready) else "screen",
            "owner_phone_set": bool(st.owner_phone), "sms_provider_ready": sms_ready,
            "large_order_total": f"{st.owner_alert_order_total:.2f}", "cooldown_seconds": st.owner_alert_cooldown_s}


# ---------------- PayPal reconciliation (Transaction Search) ----------------
PAID = ("paid", "preparing", "ready")
REPORT_LAG_HOURS = 4  # PayPal says new transactions can take up to ~3 hours to appear in reports


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.get("/reconciliation")
async def reconciliation(days: int = 7):
    """Match every paid order to PayPal's own transaction report. Read-only."""
    days = max(1, min(days, 30))
    now = _now()
    since = now - timedelta(days=days)
    try:
        txs = await core.state.paypal.search_transactions(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    except PayPalError as e:
        hint = "The PayPal app needs the Transaction search feature enabled." if e.status == 403 else "PayPal's report API did not answer."
        raise HTTPException(502, {"error": hint, "paypal_status": e.status})

    by_id, by_custom = {}, {}
    for t in txs:
        info = t.get("transaction_info", {})
        by_id[info.get("transaction_id")] = info
        if info.get("custom_field"):
            by_custom.setdefault(info["custom_field"], info)

    async with core.state.db.session() as s:
        orders = list((await s.execute(
            select(Order).where(Order.status.in_(PAID), Order.paid_at.is_not(None), Order.paid_at >= since).order_by(Order.paid_at.desc())
        )).scalars())

    rows, used = [], set()
    gross = fees = Decimal("0")
    counts = {"matched": 0, "amount_mismatch": 0, "pending_in_paypal": 0, "missing_in_paypal": 0}
    for o in orders:
        info = by_id.get(o.capture_id) or by_custom.get(o.id)
        row = {"order_id": o.id, "capture_id": o.capture_id, "order_total": f"{o.total:.2f}", "paid_at": core._iso(o.paid_at),
               "paypal_amount": None, "paypal_fee": None, "paypal_status": None}
        if info:
            used.add(info.get("transaction_id"))
            amount = Decimal(str(info.get("transaction_amount", {}).get("value", "0")))
            fee = Decimal(str((info.get("fee_amount") or {}).get("value", "0")))
            row.update(paypal_amount=f"{amount:.2f}", paypal_fee=f"{fee:.2f}", paypal_status=info.get("transaction_status"))
            row["result"] = "matched" if amount == o.total else "amount_mismatch"
            gross += amount
            fees += fee
        else:
            fresh = now - _aware(o.paid_at) < timedelta(hours=REPORT_LAG_HOURS)
            row["result"] = "pending_in_paypal" if fresh else "missing_in_paypal"
        counts[row["result"]] += 1
        rows.append(row)

    unknown = []
    for tid, info in by_id.items():
        amount = Decimal(str(info.get("transaction_amount", {}).get("value", "0")))
        code = str(info.get("transaction_event_code") or "")
        if tid not in used and amount > 0 and code.startswith("T00"):
            unknown.append({"transaction_id": tid, "amount": f"{amount:.2f}", "event_code": code,
                            "date": info.get("transaction_initiation_date"), "custom_field": info.get("custom_field")})

    return {
        "window_days": days, "generated_at": now.isoformat(), "paypal_transactions": len(txs),
        "summary": {"orders": len(orders), **counts, "unknown_in_paypal": len(unknown),
                    "gross": f"{gross:.2f}", "fees": f"{fees:.2f}", "net": f"{gross + fees:.2f}"},
        "rows": rows, "unknown": unknown,
        "note": f"PayPal's report can lag by up to about 3 hours; orders paid in the last {REPORT_LAG_HOURS} hours show as pending, not missing.",
    }
