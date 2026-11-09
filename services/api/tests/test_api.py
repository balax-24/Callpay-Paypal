"""End-to-end API tests with PayPal mocked (respx). No real network calls."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

PP = "https://api-m.sandbox.paypal.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-1")
    monkeypatch.setenv("DATABASE_URL", "")  # force SQLite fallback
    monkeypatch.setenv("SQLITE_FALLBACK_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "")
    monkeypatch.setenv("PROVIDERS_LLM", "claude")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{PP}/v1/oauth2/token").respond(200, json={"access_token": "tok", "expires_in": 3600})
        with TestClient(app) as c:
            c.mock = mock
            yield c


def _menu(client):
    biz = client.get("/businesses").json()[0]
    return biz, biz["menu"]


def test_health_uses_sqlite_fallback(client):
    h = client.get("/health").json()
    assert h["database"] == "sqlite" and h["event_bus"] == "memory" and h["paypal_configured"]


def test_order_prices_come_from_menu_and_creates_paypal_order(client):
    route = client.mock.post(f"{PP}/v2/checkout/orders").respond(
        201, json={"id": "PPORDER1", "links": [{"rel": "payer-action", "href": "https://paypal.test/pay"}]}
    )
    biz, menu = _menu(client)
    r = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": menu[0]["id"], "quantity": 2}]})
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "link_sent" and o["payment_method"] == "orders" and o["pay_link"] == "https://paypal.test/pay"
    assert o["total"] == "7.00"
    req = route.calls[0].request
    assert req.headers["PayPal-Request-Id"] == f"order-{o['id']}"


def test_order_note_is_stored_and_does_not_change_price(client):
    route = client.mock.post(f"{PP}/v2/checkout/orders").respond(
        201, json={"id": "PPNOTE1", "links": [{"rel": "payer-action", "href": "https://paypal.test/note"}]}
    )
    biz, menu = _menu(client)
    r = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": menu[0]["id"], "quantity": 2, "note": "no onions"}]})
    assert r.status_code == 200
    order = r.json()
    assert order["items"][0]["note"] == "no onions" and order["total"] == "7.00"
    body = route.calls[0].request.content.decode()
    assert '"description":"no onions"' in body


def test_tip_is_code_computed_and_added_to_paypal_item_total(client):
    route = client.mock.post(f"{PP}/v2/checkout/orders").respond(
        201, json={"id": "PPTIP1", "links": [{"rel": "payer-action", "href": "https://paypal.test/tip"}]}
    )
    biz, menu = _menu(client)
    r = client.post("/orders", json={"business_id": biz["id"], "tip_pct": 15, "lines": [{"menu_item_id": menu[0]["id"], "quantity": 2}]})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["total"] == "8.05" and order["tip"] == "1.05"
    body = __import__("json").loads(route.calls[0].request.content)
    unit = body["purchase_units"][0]
    assert unit["amount"]["value"] == "8.05"
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "8.05"
    assert next(i for i in unit["items"] if i["name"] == "Crew tip")["unit_amount"]["value"] == "1.05"


def test_tip_percentage_is_allowlisted(client):
    biz, menu = _menu(client)
    response = client.post("/orders", json={"business_id": biz["id"], "tip_pct": 17, "lines": [{"menu_item_id": menu[0]["id"], "quantity": 1}]})
    assert response.status_code == 422


def test_orders_failure_falls_back_to_invoice(client):
    client.mock.post(f"{PP}/v2/checkout/orders").respond(422, json={"name": "UNPROCESSABLE_ENTITY"})
    client.mock.post(f"{PP}/v2/invoicing/invoices").respond(201, json={"id": "INV2-1"})
    client.mock.post(f"{PP}/v2/invoicing/invoices/INV2-1/send").respond(200, json={"href": "https://paypal.test/invoice/INV2-1"})
    biz, menu = _menu(client)
    o = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": menu[1]["id"], "quantity": 1}]}).json()
    assert o["payment_method"] == "invoice" and o["paypal_ref"] == "INV2-1"
    prov = client.get("/providers").json()["payments"]
    assert any(p["provider"] == "invoice" and p["last_used"] for p in prov)


def test_unknown_menu_item_rejected(client):
    biz, _ = _menu(client)
    r = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": "nope", "quantity": 1}]})
    assert r.status_code == 400


def test_remind_link_is_rate_limited_and_only_for_unpaid_orders(client):
    client.mock.post(f"{PP}/v2/checkout/orders").respond(
        201, json={"id": "PPREMIND1", "links": [{"rel": "payer-action", "href": "https://paypal.test/remind"}]}
    )
    biz, menu = _menu(client)
    order = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": menu[0]["id"], "quantity": 1}]}).json()
    first = client.post(f"/orders/{order['id']}/remind")
    assert first.status_code == 200 and first.json()["reminder_channel"] == "screen"
    assert client.post(f"/orders/{order['id']}/remind").status_code == 429
    assert client.post("/orders/unknown/remind").status_code == 404


def test_remind_rejects_paid_orders(client):
    client.mock.post(f"{PP}/v2/checkout/orders").respond(
        201, json={"id": "PPREMIND2", "links": [{"rel": "payer-action", "href": "https://paypal.test/remind2"}]}
    )
    client.mock.post(f"{PP}/v1/notifications/verify-webhook-signature").respond(200, json={"verification_status": "SUCCESS"})
    biz, menu = _menu(client)
    order = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": menu[0]["id"], "quantity": 1}]}).json()
    headers = {
        "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-transmission-id": "t-remind", "paypal-transmission-sig": "sig", "paypal-transmission-time": "now",
    }
    event = {"id": "WH-REMIND", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"custom_id": order["id"]}}
    assert client.post("/webhooks/paypal", json=event, headers=headers).status_code == 200
    assert client.post(f"/orders/{order['id']}/remind").status_code == 409


def test_verified_webhook_marks_paid_once(client):
    client.mock.post(f"{PP}/v2/checkout/orders").respond(
        201, json={"id": "PPORDER2", "links": [{"rel": "payer-action", "href": "https://paypal.test/pay2"}]}
    )
    client.mock.post(f"{PP}/v1/notifications/verify-webhook-signature").respond(200, json={"verification_status": "SUCCESS"})
    biz, menu = _menu(client)
    o = client.post("/orders", json={"business_id": biz["id"], "lines": [{"menu_item_id": menu[0]["id"], "quantity": 1}]}).json()
    headers = {
        "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-transmission-id": "t1", "paypal-transmission-sig": "sig", "paypal-transmission-time": "now",
    }
    event = {"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"custom_id": o["id"]}}
    assert client.post("/webhooks/paypal", json=event, headers=headers).json() == {"ok": True}
    # the workflow may already have moved it on to the kitchen
    assert client.get(f"/orders/{o['id']}").json()["status"] in ("paid", "preparing", "ready")
    assert client.post("/webhooks/paypal", json=event, headers=headers).json()["duplicate"] is True


def test_unverified_webhook_rejected(client):
    r = client.post("/webhooks/paypal", json={"id": "x", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}})
    assert r.status_code == 400


def test_kill_switch(client):
    st = client.post("/providers/payments/orders/kill").json()
    assert next(p for p in st if p["provider"] == "orders")["state"] == "open"
    st = client.post("/providers/payments/orders/revive").json()
    assert next(p for p in st if p["provider"] == "orders")["state"] == "closed"


def test_audit_chain_records_provider_controls_and_verifies(client):
    assert client.post("/providers/payments/orders/kill").status_code == 200
    assert client.post("/providers/payments/orders/revive").status_code == 200
    verification = client.get("/audit/verify").json()
    assert verification["valid"] and verification["checked"] == 2
    entries = client.get("/audit").json()
    assert [entry["action"] for entry in reversed(entries)] == ["provider.kill", "provider.revive"]
    assert entries[0]["prev_hash"] == entries[1]["hash"]


def test_internal_workflow_step_requires_shared_token(client):
    call = client.post("/calls", json={}).json()
    denied = client.post(f"/internal/orders/{call['id']}/fulfil")
    assert denied.status_code == 403


def test_llm_fails_over_when_no_key(client):
    r = client.post("/llm/test", json={})
    assert r.status_code == 503  # only claude configured in this test and it has no key
