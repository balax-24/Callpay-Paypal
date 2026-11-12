"""Calls: browser call widget API, speech endpoints, and Twilio / Telnyx phone webhooks.

Phone path:  caller -> Twilio (or Telnyx TeXML) -> /voice/{carrier}/incoming -> <Gather speech> -> /turn
             -> agent -> <Say>.  While waiting for payment the call loops on /wait, polling the order,
             so the caller hears "got your payment" the moment the PayPal webhook / capture lands.
Browser path: the dashboard /call page uses /calls/* plus /voice/stt + /voice/tts (or the browser's own
             speech engines as the last fallback).
"""

import asyncio
import copy
import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import main as core
from . import routes_ops as ops
from .agents.runtime import CheckoutBlocked, Planner, Turn
from .db import Business, Call, Order, SupportCase
from .providers.chain import AllProvidersFailed

from prometheus_client import Counter, Histogram

log = logging.getLogger("callpay.voice")
TURN_SECONDS = Histogram("callpay_turn_seconds", "Agent reply latency per caller turn", ["agent", "brain"],
                         buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15))
CALLS = Counter("callpay_calls_total", "Calls by channel and outcome", ["channel", "status"])
router = APIRouter()
_locks: dict[str, asyncio.Lock] = {}
_planner: Planner | None = None


def planner() -> Planner:
    global _planner
    if _planner is None or _planner.llm.chain is not core.state.llm:
        _planner = Planner(core.state.llm)
    return _planner


class ApiTools:
    """The tools the agents may use. Every money value comes from the database."""

    def __init__(self, business: dict):
        self.business = business

    async def place_order(self, lines: list[dict], caller: str | None, call_id: str, tip_pct: int = 0) -> dict:
        try:
            return await core.create_order(core.CreateOrder(
                business_id=self.business["id"], customer_phone=caller, call_id=call_id, tip_pct=tip_pct,
                lines=[core.OrderLine(**line) for line in lines]))
        except HTTPException as e:  # fraud cap / rate limit: tell the caller plainly instead of blaming PayPal
            if isinstance(e.detail, dict) and e.detail.get("say"):
                raise CheckoutBlocked(e.detail["say"]) from e
            raise

    async def order_status(self, order_id: str) -> dict:
        try:
            return await core.get_order(order_id)
        except HTTPException:
            return {}

    async def send_pay_link(self, phone: str | None, url: str, order: dict) -> str:
        if not phone:
            return "screen"
        return await core._send_sms(phone, f"{self.business['name']}: pay ${order['total']} securely with PayPal: {url}")

    async def open_support_case(self, call_id: str, order_id: str | None, text: str) -> None:
        async with core.state.db.session() as s:
            s.add(SupportCase(call_id=call_id, order_id=order_id, text=text[:1000]))
            await s.commit()


async def _business(business_id: str | None) -> dict:
    async with core.state.db.session() as s:
        b = await s.get(Business, business_id) if business_id else (await s.execute(select(Business).limit(1))).scalar_one_or_none()
        if not b:
            raise HTTPException(404, "business not found")
        return {"id": b.id, "name": b.name, "currency": b.currency,
                "menu": [{"id": m.id, "name": m.name, "price": str(m.price)} for m in b.menu]}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _call_json(c: Call) -> dict:
    return {"id": c.id, "business_id": c.business_id, "channel": c.channel, "caller": c.caller, "status": c.status,
            "stage": (c.state or {}).get("stage"), "order_id": c.order_id, "transcript": c.transcript,
            "pay_link": (c.state or {}).get("pay_link"), "total": (c.state or {}).get("total"),
            "started_at": core._iso(c.started_at), "ended_at": core._iso(c.ended_at)}


async def start_call(business_id: str | None, channel: str, caller: str | None, external_id: str | None = None) -> tuple[Call, str]:
    await ops.guard_new_call(caller)  # per-caller rate limit + fraud rule
    biz = await _business(business_id)
    say = planner().greeting(biz)
    async with core.state.db.session() as s:
        c = Call(business_id=biz["id"], channel=channel, caller=caller, external_id=external_id,
                 state={"stage": "ordering", "cart": {}},
                 transcript=[{"role": "agent", "text": say, "agent": "planner", "ts": _now()}])
        s.add(c)
        await s.commit()
    await core.state.bus.publish("call.started", {"call_id": c.id, "channel": channel, "caller": caller})
    await core.state.bus.publish("call.transcript", {"call_id": c.id, "role": "agent", "text": say})
    return c, say


async def run_turn(call_id: str, text: str) -> tuple[Turn, Call]:
    lock = _locks.setdefault(call_id, asyncio.Lock())
    async with lock:
        async with core.state.db.session() as s:
            c = await s.get(Call, call_id)
            if not c:
                raise HTTPException(404, "call not found")
            if c.status != "active":
                raise HTTPException(409, f"call is {c.status}")
            biz = await _business(c.business_id)
            st = copy.deepcopy(c.state or {})
            history = list(c.transcript or [])
            if len(history) >= 2 * core.state.settings.rate_turns_per_call:  # per-call turn limit
                turn = Turn("We've been on the line a while, so I'll let you go. Please call back to finish your order.",
                            "planner", end_call=True)
            else:
                t0 = time.perf_counter()
                turn = await planner().turn(text, st, ApiTools(biz), history, c.id, c.caller)
                TURN_SECONDS.labels(turn.agent, turn.llm or "rules").observe(time.perf_counter() - t0)
            history += [{"role": "caller", "text": text[:600], "ts": _now()},
                        {"role": "agent", "text": turn.say, "agent": turn.agent, "llm": turn.llm, "ts": _now()}]
            c.state, c.transcript = st, history
            c.order_id = st.get("order_id") or c.order_id
            await s.commit()
        await core.state.bus.publish("call.transcript", {"call_id": call_id, "role": "caller", "text": text[:600]})
        await core.state.bus.publish("call.transcript", {"call_id": call_id, "role": "agent", "text": turn.say,
                                                         "agent": turn.agent, "llm": turn.llm})
        for ev in turn.events:
            await core.state.bus.publish(ev.pop("topic"), ev)
        if turn.end_call:
            await end_call(call_id)
        return turn, c


async def poll_payment(call_id: str) -> str | None:
    """If the order got paid since the last turn, return the line to say (once)."""
    lock = _locks.setdefault(call_id, asyncio.Lock())
    async with lock:
        async with core.state.db.session() as s:
            c = await s.get(Call, call_id)
            if not c or (c.state or {}).get("stage") != "awaiting_payment" or not c.order_id:
                return None
            o = await s.get(Order, c.order_id)
            if not o or o.status not in ("paid", "preparing", "ready"):
                return None
            st = copy.deepcopy(c.state)
            say = await planner().payment_confirmed_line(st, {"total": str(o.total)})
            c.state = st
            c.transcript = [*c.transcript, {"role": "agent", "text": say, "agent": "payments", "ts": _now()}]
            await s.commit()
    await core.state.bus.publish("call.transcript", {"call_id": call_id, "role": "agent", "text": say, "agent": "payments"})
    return say


async def end_call(call_id: str) -> Call | None:
    async with core.state.db.session() as s:
        c = await s.get(Call, call_id)
        if not c or c.status != "active":
            return c
        st = c.state or {}
        unpaid = st.get("stage") == "awaiting_payment" or (st.get("cart") and st.get("stage") in ("ordering", "confirming", "tipping"))
        c.status = "abandoned" if unpaid else "ended"
        c.ended_at = datetime.now(timezone.utc)
        await s.commit()
    try:
        key = f"transcripts/{c.started_at:%Y/%m/%d}/{c.id}.json"
        st = {**(c.state or {}), "pay_link": None}
        await core.state.store.put_json(key, {**_call_json(c), "state": st})
    except Exception as e:  # noqa: BLE001 - archiving must never break hang-up
        log.warning("transcript archive failed: %s", e)
    CALLS.labels(c.channel, c.status).inc()
    await core.state.bus.publish("call.ended", {"call_id": call_id, "status": c.status, "order_id": c.order_id})
    if c.status == "abandoned":
        await core.state.bus.publish("call.abandoned", {"call_id": call_id, "order_id": c.order_id})
    _locks.pop(call_id, None)
    return c


# ---------------- browser call API ----------------
class StartCall(BaseModel):
    business_id: str | None = None
    caller: str | None = Field(default=None, max_length=32)
    channel: str = "web"
    language: str = Field(default="en", pattern="^(en|hi|ta|es)$")


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)


@router.post("/calls")
async def create_call(body: StartCall):
    c, say = await start_call(body.business_id, body.channel if body.channel in ("web",) else "web", body.caller)
    if body.language != "en":
        async with core.state.db.session() as s:
            persisted = await s.get(Call, c.id)
            persisted.state = {**(persisted.state or {}), "language": body.language}
            await s.commit()
            c = persisted
    return {**_call_json(c), "say": say}


@router.post("/calls/{call_id}/turn")
async def call_turn(call_id: str, body: TurnIn):
    turn, c = await run_turn(call_id, body.text)
    return {"say": turn.say, "agent": turn.agent, "llm": turn.llm, "end_call": turn.end_call, "call": _call_json(c)}


@router.post("/calls/{call_id}/poll")
async def call_poll(call_id: str):
    return {"say": await poll_payment(call_id)}


@router.post("/calls/{call_id}/end")
async def call_end(call_id: str):
    c = await end_call(call_id)
    if not c:
        raise HTTPException(404, "call not found")
    return _call_json(c)


@router.get("/calls")
async def list_calls(limit: int = 100):
    async with core.state.db.session() as s:
        rows = (await s.execute(select(Call).order_by(Call.started_at.desc()).limit(min(limit, 500)))).scalars()
        return [_call_json(c) for c in rows]


@router.get("/calls/{call_id}")
async def get_call(call_id: str):
    async with core.state.db.session() as s:
        c = await s.get(Call, call_id)
        if not c:
            raise HTTPException(404, "call not found")
        return _call_json(c)


# ---------------- speech ----------------
@router.post("/voice/stt")
async def stt(audio: UploadFile = File(...)):
    data = await audio.read()
    if len(data) > 10_000_000:
        raise HTTPException(413, "audio too large")
    try:
        text, used = await core.state.voice["stt"].call(lambda p: p.transcribe(data, audio.content_type or "audio/webm"))
    except AllProvidersFailed as e:
        raise HTTPException(503, {"error": "no speech-to-text provider available; use browser speech", "details": e.errors})
    return {"text": text, "provider": used}


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)


@router.post("/voice/tts")
async def tts(body: TTSIn):
    try:
        (audio, mime), used = await core.state.voice["tts"].call(lambda p: p.speak(body.text))
    except AllProvidersFailed as e:
        raise HTTPException(503, {"error": "no text-to-speech provider available; use browser speech", "details": e.errors})
    return Response(audio, media_type=mime, headers={"X-Provider": used, "Access-Control-Expose-Headers": "X-Provider"})


# ---------------- Twilio / Telnyx (TeXML is TwiML-compatible) ----------------
CARRIERS = ("twilio", "telnyx")
WAIT_LOOPS = 60  # ~3 minutes of waiting for payment


def _twiml(*verbs: str) -> Response:
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(verbs) + "</Response>", media_type="application/xml")


def _say(text: str) -> str:
    return f'<Say voice="Polly.Joanna">{escape(text)}</Say>'


def _gather(call_id: str, inner: str, timeout: int = 5) -> str:
    return (f'<Gather input="speech" action="turn?call={call_id}" method="POST" speechTimeout="auto" '
            f'timeout="{timeout}" language="en-US">{inner}</Gather>')


async def _form(request: Request, carrier: str) -> dict:
    form = dict((await request.form()).items())
    token = core.state.settings.twilio_auth_token
    if carrier == "twilio" and token and core.state.settings.app_url.startswith("https"):
        url = core.state.settings.app_url.rstrip("/") + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        signed = url + "".join(k + str(form[k]) for k in sorted(form))
        expected = base64.b64encode(hmac.new(token.encode(), signed.encode(), hashlib.sha1).digest()).decode()
        if not hmac.compare_digest(expected, request.headers.get("x-twilio-signature", "")):
            raise HTTPException(403, "bad Twilio signature")
    return form


@router.post("/voice/{carrier}/incoming")
async def phone_incoming(carrier: str, request: Request):
    if carrier not in CARRIERS:
        raise HTTPException(404)
    form = await _form(request, carrier)
    try:
        c, say = await start_call(request.query_params.get("business_id"), carrier, form.get("From"), form.get("CallSid"))
    except HTTPException as e:
        if e.status_code == 429 and isinstance(e.detail, dict):
            return _twiml(_say(e.detail.get("say", "Please try again later.")), "<Hangup/>")
        raise
    return _twiml(_gather(c.id, _say(say)), f'<Redirect method="POST">turn?call={c.id}&amp;silence=1</Redirect>')


@router.post("/voice/{carrier}/turn")
async def phone_turn(carrier: str, request: Request, call: str, silence: int = 0):
    if carrier not in CARRIERS:
        raise HTTPException(404)
    form = await _form(request, carrier)
    speech = (form.get("SpeechResult") or "").strip()
    if not speech:
        if silence >= 2:
            await end_call(call)
            return _twiml(_say("I didn't hear anything, so I'll hang up. Call back anytime!"), "<Hangup/>")
        return _twiml(_gather(call, _say("Are you still there? What would you like to order?")),
                      f'<Redirect method="POST">turn?call={call}&amp;silence={silence + 1}</Redirect>')
    try:
        turn, c = await run_turn(call, speech)
    except HTTPException:
        return _twiml(_say("Sorry, this call has ended."), "<Hangup/>")
    if turn.end_call:
        return _twiml(_say(turn.say), "<Hangup/>")
    if (c.state or {}).get("stage") == "awaiting_payment":
        return _twiml(_say(turn.say), f'<Redirect method="POST">wait?call={call}&amp;n=0</Redirect>')
    return _twiml(_gather(call, _say(turn.say)), f'<Redirect method="POST">turn?call={call}&amp;silence=1</Redirect>')


@router.post("/voice/{carrier}/wait")
async def phone_wait(carrier: str, request: Request, call: str, n: int = 0):
    """Hold loop while the caller pays on their phone. Speaking interrupts it (goes to /turn)."""
    if carrier not in CARRIERS:
        raise HTTPException(404)
    await _form(request, carrier)
    said = await poll_payment(call)
    if said:
        return _twiml(_gather(call, _say(said + " Anything else?")), "<Hangup/>")
    if n >= WAIT_LOOPS:
        await end_call(call)
        return _twiml(_say("I'll let you go now. The PayPal link stays valid, and I'll text you a reminder. Bye!"), "<Hangup/>")
    hint = _say("Still waiting for PayPal. Take your time.") if n and n % 10 == 0 else ""
    return _twiml(_gather(call, hint + '<Pause length="3"/>', timeout=1),
                  f'<Redirect method="POST">wait?call={call}&amp;n={n + 1}</Redirect>')


@router.post("/voice/{carrier}/status")
async def phone_status(carrier: str, request: Request):
    """Carrier status callback: the caller hung up."""
    form = await _form(request, carrier)
    if form.get("CallStatus") in ("completed", "busy", "failed", "no-answer", "canceled") and form.get("CallSid"):
        async with core.state.db.session() as s:
            c = (await s.execute(select(Call).where(Call.external_id == form["CallSid"]))).scalar_one_or_none()
        if c:
            await end_call(c.id)
    return {"ok": True}
