"""Owner operations: menu editor, fraud guard + rate limits, owner alerts, PayPal reconciliation."""

from .test_calls import HEADERS, PP, _wait, client  # noqa: F401  (fixture)

CALLER = "+15550009999"


def _biz(client):
    return client.get("/businesses").json()[0]


def _order_call(client, caller, what):
    """Run a call up to the 'yes' that asks for the PayPal link; return the final turn."""
    cid = client.post("/calls", json={"caller": caller}).json()["id"]
    client.post(f"/calls/{cid}/turn", json={"text": what})
    client.post(f"/calls/{cid}/turn", json={"text": "that's it"})
    client.post(f"/calls/{cid}/turn", json={"text": "no tip"})
    return client.post(f"/calls/{cid}/turn", json={"text": "yes"}).json()


# ---------------- menu editor ----------------
def test_menu_editor_changes_what_the_agent_sells(client):
    biz = _biz(client)
    r = client.post(f"/businesses/{biz['id']}/menu", json={"name": "Churro", "price": "2.00"})
    assert r.status_code == 200 and r.json()["price"] == "2.00"
    churro = r.json()["id"]
    assert client.post(f"/businesses/{biz['id']}/menu", json={"name": "churro", "price": "9.00"}).status_code == 409
    assert client.post(f"/businesses/{biz['id']}/menu", json={"name": "Free lunch", "price": "0"}).status_code == 422
    assert client.put(f"/menu/{churro}", json={"price": "2.50"}).json()["price"] == "2.50"

    # the very next call uses the new item and the new price
    cid = client.post("/calls", json={}).json()["id"]
    t = client.post(f"/calls/{cid}/turn", json={"text": "three churros please"}).json()
    assert "$7.50" in t["say"]

    assert client.delete(f"/menu/{churro}").json() == {"ok": True}
    assert all(m["name"] != "Churro" for m in _biz(client)["menu"])
    actions = [e["action"] for e in client.get("/audit").json()]
    assert {"menu.item_added", "menu.item_changed", "menu.item_removed"} <= set(actions)


def test_menu_keeps_at_least_one_item(client):
    menu = _biz(client)["menu"]
    for m in menu[:-1]:
        assert client.delete(f"/menu/{m['id']}").status_code == 200
    assert client.delete(f"/menu/{menu[-1]['id']}").status_code == 409
    assert client.put("/menu/nope", json={"price": "1.00"}).status_code == 404


# ---------------- fraud guard + rate limits ----------------
def test_repeat_caller_is_flagged_capped_and_rate_limited(client):
    for _ in range(4):
        assert client.post("/calls", json={"caller": CALLER}).status_code == 200
    assert client.get("/fraud/flags").json()["flags"] == []

    # 5th call in the window -> flagged; over-cap checkout is refused in plain words (4 x $9.00 = $36 > $30)
    t = _order_call(client, CALLER, "four veggie burritos")
    flags = client.get("/fraud/flags").json()["flags"]
    assert len(flags) == 1 and flags[0]["caller"] == CALLER and flags[0]["in_effect"] and flags[0]["source"] == "rule"
    assert "$30.00" in t["say"] and t["call"]["stage"] != "awaiting_payment" and t["call"]["order_id"] is None

    # under the cap still works for a flagged caller
    t = _order_call(client, CALLER, "one horchata")
    assert t["call"]["stage"] == "awaiting_payment"

    # refunds for a flagged caller always go to the owner, even small ones
    client.mock.post(f"{PP}/v2/payments/captures/CAPF/refund").respond(201, json={"id": "RFF"})
    order_id = t["call"]["order_id"]
    client.post("/webhooks/paypal", json={"id": "EF1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
                                          "resource": {"id": "CAPF", "custom_id": order_id}}, headers=HEADERS)
    refund = client.post(f"/orders/{order_id}/refund", json={"amount": "1.00"}).json()
    assert refund["status"] == "pending_approval" and "flagged" in refund["policy"]["reasons"][0]

    # hard stop after 8 calls in the window (7th and 8th are fine, 9th is refused)
    assert client.post("/calls", json={"caller": CALLER}).status_code == 200
    assert client.post("/calls", json={"caller": CALLER}).status_code == 200
    r = client.post("/calls", json={"caller": CALLER})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"

    # the owner can clear the flag; callers without a number are never limited
    assert client.post(f"/fraud/flags/{flags[0]['id']}/clear").json()["active"] is False
    assert client.get("/fraud/flags").json()["flags"][0]["in_effect"] is False
    assert client.post("/calls", json={}).status_code == 200


def test_checkout_rate_limit_and_manual_flag(client):
    biz = _biz(client)
    body = {"business_id": biz["id"], "customer_phone": "+15550007777", "lines": [{"menu_item_id": biz["menu"][3]["id"], "quantity": 1}]}
    for _ in range(3):
        assert client.post("/orders", json=body).status_code == 200
    r = client.post("/orders", json=body)
    assert r.status_code == 429 and "limit" in r.json()["detail"]["say"]

    f = client.post("/fraud/flags", json={"caller": "+15550006666", "reason": "chargeback last week"}).json()
    assert f["source"] == "owner"
    big = {"business_id": biz["id"], "customer_phone": "+15550006666", "lines": [{"menu_item_id": biz["menu"][2]["id"], "quantity": 5}]}
    r = client.post("/orders", json=big)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "fraud_cap"


def test_phone_caller_hears_the_rate_limit(client):
    for i in range(8):
        client.post("/voice/twilio/incoming", data={"From": "+15550005555", "CallSid": f"CA{i}"})
    r = client.post("/voice/twilio/incoming", data={"From": "+15550005555", "CallSid": "CA9"})
    assert r.status_code == 200 and "<Hangup/>" in r.text and "try again" in r.text


# ---------------- owner alerts ----------------
def test_owner_alert_when_approval_is_needed(client):
    biz = _biz(client)
    staff = client.get("/staff").json()
    client.post("/payouts", json={"business_id": biz["id"], "lines": [{"staff_id": staff[0]["id"], "amount": "120.00"}]})
    data = _wait(lambda: (d := client.get("/alerts").json())["alerts"] and d)
    a = data["alerts"][0]
    assert a["kind"] == "payout_approval" and "$120.00" in a["message"] and a["channel"] == "screen"
    assert data["delivery"] == "screen" and data["owner_phone_set"] is False

    # a second one inside the cooldown is not sent again
    client.post("/payouts", json={"business_id": biz["id"], "lines": [{"staff_id": staff[0]["id"], "amount": "130.00"}]})
    assert len(client.get("/alerts").json()["alerts"]) == 1

    # a different kind still gets through
    client.post("/fraud/flags", json={"caller": "+15550004444"})
    _wait(lambda: len(client.get("/alerts").json()["alerts"]) == 2)


# ---------------- reconciliation ----------------
def _paid_order(client, capture, event_id, qty=1):
    biz = _biz(client)
    o = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": biz["menu"][0]["id"], "quantity": qty}]}).json()
    client.post("/webhooks/paypal", json={"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED",
                                          "resource": {"id": capture, "custom_id": o["id"]}}, headers=HEADERS)
    return o


def _tx(tid, amount, fee="-0.50", code="T0006", custom=None):
    return {"transaction_info": {"transaction_id": tid, "transaction_amount": {"value": amount}, "fee_amount": {"value": fee},
                                 "transaction_event_code": code, "transaction_status": "S", "custom_field": custom,
                                 "transaction_initiation_date": "2026-11-12T00:00:00+0000"}}


def test_reconciliation_matches_orders_to_paypal_report(client):
    ok = _paid_order(client, "CAP-A", "ER1")            # $3.50, in the report
    wrong = _paid_order(client, "CAP-B", "ER2", qty=2)  # $7.00, report says 6.00
    late = _paid_order(client, "CAP-C", "ER3")          # not in the report yet
    route = client.mock.get(f"{PP}/v1/reporting/transactions").respond(200, json={"total_pages": 1, "transaction_details": [
        _tx("CAP-A", "3.50", "-0.42"), _tx("CAP-B", "6.00"), _tx("STRAY-1", "25.00"), _tx("PAYOUT-1", "-0.98", "0.00", "T0400"),
    ]})
    r = client.get("/reconciliation", params={"days": 7})
    assert r.status_code == 200, r.text
    d = r.json()
    by = {row["order_id"]: row for row in d["rows"]}
    assert by[ok["id"]]["result"] == "matched" and by[ok["id"]]["paypal_fee"] == "-0.42"
    assert by[wrong["id"]]["result"] == "amount_mismatch"
    assert by[late["id"]]["result"] == "pending_in_paypal"
    s = d["summary"]
    assert (s["matched"], s["amount_mismatch"], s["pending_in_paypal"], s["missing_in_paypal"]) == (1, 1, 1, 0)
    assert s["unknown_in_paypal"] == 1 and d["unknown"][0]["transaction_id"] == "STRAY-1"  # the payout is not "unknown income"
    assert s["gross"] == "9.50" and s["fees"] == "-0.92" and s["net"] == "8.58"
    assert "start_date" in str(route.calls[0].request.url)


def test_reconciliation_explains_missing_permission(client):
    client.mock.get(f"{PP}/v1/reporting/transactions").respond(403, json={"name": "NOT_AUTHORIZED"})
    r = client.get("/reconciliation")
    assert r.status_code == 502 and "Transaction search" in r.json()["detail"]["error"]


# ---------------- crew records ----------------
def test_fix_crew_email_rejects_pasted_env_lines(client):
    staff = client.get("/staff").json()[1]
    bad = "sb-x@personal.example.comINTERNAL_API_TOKEN=secret"
    assert client.patch(f"/staff/{staff['id']}", json={"paypal_email": bad}).status_code == 422
    assert client.post("/staff", json={"business_id": _biz(client)["id"], "name": "X", "paypal_email": bad}).status_code == 422
    r = client.patch(f"/staff/{staff['id']}", json={"paypal_email": "sb-hlwxi53793408@personal.example.com"})
    assert r.status_code == 200 and r.json()["paypal_email"] == "sb-hlwxi53793408@personal.example.com"
    assert any(e["action"] == "staff.updated" for e in client.get("/audit").json())
    assert client.patch(f"/staff/{staff['id']}", json={"active": False}).json()["active"] is False
    assert all(s["id"] != staff["id"] for s in client.get("/staff").json())
    assert client.patch("/staff/nope", json={"active": False}).status_code == 404


def test_seed_skips_malformed_crew_emails(tmp_path, monkeypatch):
    import respx
    from fastapi.testclient import TestClient

    for k, v in {
        "PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret", "DATABASE_URL": "", "KAFKA_BOOTSTRAP": "",
        "SQLITE_FALLBACK_URL": f"sqlite+aiosqlite:///{tmp_path}/seed.db", "PROVIDERS_LLM": "claude", "TEMPORAL_ADDRESS": "",
        "CLICKHOUSE_URL": "", "LOCAL_STORAGE_DIR": str(tmp_path / "store"),
        "CREW_EMAILS": "good@personal.example.com,bad@personal.example.comINTERNAL_API_TOKEN=leak",
    }.items():
        monkeypatch.setenv(k, v)
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with respx.mock(assert_all_called=False), TestClient(app) as c:
        emails = [s["paypal_email"] for s in c.get("/staff").json()]
    assert "good@personal.example.com" in emails
    assert not any("TOKEN" in e for e in emails)
