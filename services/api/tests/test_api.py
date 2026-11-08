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


def test_llm_fails_over_when_no_key(client):
    r = client.post("/llm/test", json={})
    assert r.status_code == 503  # only claude configured in this test and it has no key
