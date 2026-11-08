"""Crew payouts: policy engine, approval queue, PayPal Payouts idempotency, fallback to queue, webhooks."""

from decimal import Decimal

from app.policy import evaluate_payout

from .test_api import PP, client  # noqa: F401  (fixture)

LIMITS = dict(auto_limit=Decimal("50"), max_total=Decimal("1000"), max_item=Decimal("500"))


def _item(email, amount):
    return {"email": email, "name": email, "amount": amount}


def test_policy_auto_approval_deny():
    assert evaluate_payout([_item("a@x.io", "20"), _item("b@x.io", "30")], **LIMITS).decision == "auto"
    assert evaluate_payout([_item("a@x.io", "51")], **LIMITS).decision == "approval"
    assert evaluate_payout([_item("a@x.io", "600")], **LIMITS).decision == "deny"
    assert evaluate_payout([_item("a@x.io", "5"), _item("A@x.io", "5")], **LIMITS).decision == "deny"
    assert evaluate_payout([], **LIMITS).decision == "deny"


def _setup(client):
    biz = client.get("/businesses").json()[0]
    staff = client.get("/staff", params={"business_id": biz["id"]}).json()
    return biz, staff


def _payout(client, biz, lines):
    return client.post("/payouts", json={"business_id": biz["id"], "lines": lines, "memo": "Friday tips"})


def test_seeded_staff_and_add_staff(client):
    biz, staff = _setup(client)
    assert len(staff) == 2
    r = client.post("/staff", json={"business_id": biz["id"], "name": "Ana", "paypal_email": "ana@example.com"})
    assert r.status_code == 200
    assert client.post("/staff", json={"business_id": biz["id"], "name": "Bad", "paypal_email": "nope"}).status_code == 422


def test_small_payout_auto_sends_with_idempotency(client):
    route = client.mock.post(f"{PP}/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "BATCH1"}})
    biz, staff = _setup(client)
    p = _payout(client, biz, [{"staff_id": staff[0]["id"], "amount": "20.00"}, {"staff_id": staff[1]["id"], "amount": "15.50"}]).json()
    assert p["status"] == "sent" and p["paypal_batch_id"] == "BATCH1" and p["total"] == "35.50"
    assert p["policy"]["decision"] == "auto" and p["decided_by"] == "policy"
    req = route.calls[0].request
    assert req.headers["PayPal-Request-Id"] == f"payout-{p['id']}"
    import json

    body = json.loads(req.content)
    assert body["sender_batch_header"]["sender_batch_id"] == p["id"]
    assert [i["amount"]["value"] for i in body["items"]] == ["20.00", "15.50"]


def test_large_payout_waits_for_owner_then_sends(client):
    route = client.mock.post(f"{PP}/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "BATCH2"}})
    biz, staff = _setup(client)
    p = _payout(client, biz, [{"staff_id": staff[0]["id"], "amount": "120.00"}]).json()
    assert p["status"] == "pending_approval" and not route.called
    assert [x["id"] for x in client.get("/approvals").json()["payouts"]] == [p["id"]]
    p = client.post(f"/payouts/{p['id']}/approve", json={"by": "rosa"}).json()
    assert p["status"] == "sent" and p["decided_by"] == "rosa" and route.called
    assert client.post(f"/payouts/{p['id']}/approve").status_code == 409
    assert client.get("/approvals").json()["payouts"] == []


def test_reject_and_deny(client):
    biz, staff = _setup(client)
    p = _payout(client, biz, [{"staff_id": staff[0]["id"], "amount": "99.00"}]).json()
    assert client.post(f"/payouts/{p['id']}/reject").json()["status"] == "rejected"
    denied = _payout(client, biz, [{"staff_id": staff[0]["id"], "amount": "700.00"}]).json()
    assert denied["status"] == "rejected" and denied["policy"]["decision"] == "deny"
    assert _payout(client, biz, [{"staff_id": "ghost", "amount": "1.00"}]).status_code == 400


def test_paypal_failure_requeues_for_approval(client):
    client.mock.post(f"{PP}/v1/payments/payouts").respond(422, json={"name": "INSUFFICIENT_FUNDS"})
    biz, staff = _setup(client)
    p = _payout(client, biz, [{"staff_id": staff[0]["id"], "amount": "10.00"}]).json()
    assert p["status"] == "pending_approval" and "INSUFFICIENT_FUNDS" in p["error"]


def test_payout_webhook_completes_batch(client):
    client.mock.post(f"{PP}/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "BATCH3"}})
    client.mock.post(f"{PP}/v1/notifications/verify-webhook-signature").respond(200, json={"verification_status": "SUCCESS"})
    biz, staff = _setup(client)
    p = _payout(client, biz, [{"staff_id": staff[0]["id"], "amount": "5.00"}]).json()
    headers = {
        "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-transmission-id": "t1", "paypal-transmission-sig": "sig", "paypal-transmission-time": "now",
    }
    item = {"id": "WH-P1", "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
            "resource": {"payout_batch_id": "BATCH3", "transaction_status": "SUCCESS", "payout_item": {"sender_item_id": p["items"][0]["item_id"]}}}
    batch = {"id": "WH-P2", "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS", "resource": {"batch_header": {"payout_batch_id": "BATCH3"}}}
    assert client.post("/webhooks/paypal", json=item, headers=headers).status_code == 200
    assert client.post("/webhooks/paypal", json=batch, headers=headers).status_code == 200
    got = next(x for x in client.get("/payouts").json() if x["id"] == p["id"])
    assert got["status"] == "completed" and got["items"][0]["paypal_status"] == "SUCCESS"
