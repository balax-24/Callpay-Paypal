"""PayPal REST adapter: OAuth token cache, retries, idempotency, Orders, Payouts, webhook verification.

Fallback for collecting payment: Orders checkout link -> Invoicing (pay link in the invoice).
Every write carries a PayPal-Request-Id derived from our own order id, so retries and
failover can never create a duplicate charge or payout.
"""

import asyncio
import time
from decimal import Decimal
from typing import Any

import httpx

from ..config import Settings


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"PayPal API error {status}: {body}")
        self.status = status
        self.body = body


RETRYABLE = {408, 429, 500, 502, 503, 504}


class PayPalClient:
    def __init__(self, s: Settings, http: httpx.AsyncClient):
        self.s = s
        self.http = http
        self._token: str | None = None
        self._token_exp = 0.0
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return bool(self.s.paypal_client_id and self.s.paypal_client_secret)

    async def _get_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            r = await self.http.post(
                f"{self.s.paypal_base_url}/v1/oauth2/token",
                auth=(self.s.paypal_client_id, self.s.paypal_client_secret),
                data={"grant_type": "client_credentials"},
            )
            if r.status_code != 200:
                raise PayPalError(r.status_code, r.text)
            data = r.json()
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 3000))
            return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        request_id: str | None = None,
        retries: int = 3,
    ) -> dict:
        for attempt in range(retries + 1):
            token = await self._get_token()
            headers = {"Authorization": f"Bearer {token}", "Prefer": "return=representation"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            try:
                r = await self.http.request(
                    method, f"{self.s.paypal_base_url}{path}", json=json, params=params, headers=headers
                )
            except httpx.TransportError:
                if attempt == retries:
                    raise
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if r.status_code == 401 and attempt < retries:
                self._token = None  # token expired/revoked
                continue
            if r.status_code in RETRYABLE and attempt < retries:
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if r.status_code >= 400:
                raise PayPalError(r.status_code, r.text)
            return r.json() if r.content else {}
        raise PayPalError(0, "retries exhausted")

    # ---------- Orders (primary way to collect payment) ----------
    async def create_order(
        self,
        *,
        reference_id: str,
        amount: Decimal,
        currency: str,
        description: str,
        items: list[dict],
        return_url: str,
        cancel_url: str,
    ) -> dict:
        item_total = sum(Decimal(i["unit_amount"]) * int(i["quantity"]) for i in items)
        if item_total != amount:
            raise ValueError(f"PayPal order item total {item_total:.2f} does not match payable amount {amount:.2f}")
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "custom_id": reference_id,
                    "description": description[:127],
                    "amount": {
                        "currency_code": currency,
                        "value": f"{amount:.2f}",
                        "breakdown": {"item_total": {"currency_code": currency, "value": f"{item_total:.2f}"}},
                    },
                    "items": [
                        {
                            "name": i["name"][:127],
                            "quantity": str(i["quantity"]),
                            "unit_amount": {"currency_code": currency, "value": f"{Decimal(i['unit_amount']):.2f}"},
                            **({"description": i["note"][:127]} if i.get("note") else {}),
                        }
                        for i in items
                    ],
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        return await self.request("POST", "/v2/checkout/orders", json=body, request_id=f"order-{reference_id}")

    async def capture_order(self, paypal_order_id: str, reference_id: str) -> dict:
        return await self.request(
            "POST", f"/v2/checkout/orders/{paypal_order_id}/capture", json={}, request_id=f"capture-{reference_id}"
        )

    async def get_order(self, paypal_order_id: str) -> dict:
        return await self.request("GET", f"/v2/checkout/orders/{paypal_order_id}")

    @staticmethod
    def approval_link(order: dict) -> str | None:
        for link in order.get("links", []):
            if link.get("rel") in ("payer-action", "approve"):
                return link["href"]
        return None

    # ---------- Invoicing (fallback way to collect payment) ----------
    async def create_and_send_invoice(
        self, *, reference_id: str, currency: str, items: list[dict], note: str
    ) -> dict:
        draft = await self.request(
            "POST",
            "/v2/invoicing/invoices",
            json={
                "detail": {"currency_code": currency, "reference": reference_id, "note": note[:4000]},
                "items": [
                    {
                        "name": i["name"][:200],
                        "quantity": str(i["quantity"]),
                        "unit_amount": {"currency_code": currency, "value": f"{Decimal(i['unit_amount']):.2f}"},
                        **({"description": i["note"][:127]} if i.get("note") else {}),
                    }
                    for i in items
                ],
            },
            request_id=f"invoice-{reference_id}",
        )
        invoice_id = draft.get("id") or draft["href"].rsplit("/", 1)[-1]
        sent = await self.request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/send",
            json={"send_to_recipient": False},
            request_id=f"invoice-send-{reference_id}",
        )
        return {"id": invoice_id, "pay_link": sent.get("href")}

    # ---------- Payouts ----------
    async def create_payout(self, *, batch_id: str, currency: str, items: list[dict], subject: str) -> dict:
        return await self.request(
            "POST",
            "/v1/payments/payouts",
            json={
                "sender_batch_header": {"sender_batch_id": batch_id, "email_subject": subject},
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "receiver": i["email"],
                        "amount": {"currency": currency, "value": f"{Decimal(i['amount']):.2f}"},
                        "sender_item_id": i["item_id"],
                        "note": i.get("note", "")[:4000],
                    }
                    for i in items
                ],
            },
            request_id=f"payout-{batch_id}",
        )

    # ---------- Refunds ----------
    async def refund_capture(self, capture_id: str, *, amount: Decimal, currency: str, refund_id: str, note: str) -> dict:
        return await self.request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            json={"amount": {"value": f"{amount:.2f}", "currency_code": currency}, "note_to_payer": note[:255]},
            request_id=f"refund-{refund_id}",
        )

    # ---------- Disputes ----------
    async def get_dispute(self, dispute_id: str) -> dict:
        return await self.request("GET", f"/v1/customer/disputes/{dispute_id}")

    async def provide_dispute_evidence(self, dispute_id: str, notes: str) -> dict:
        """Submit text evidence (the call transcript summary) as a multipart request."""
        import json as _json

        token = await self._get_token()
        r = await self.http.post(
            f"{self.s.paypal_base_url}/v1/customer/disputes/{dispute_id}/provide-evidence",
            headers={"Authorization": f"Bearer {token}"},
            files={"input": (None, _json.dumps({"evidences": [{"evidence_type": "OTHER", "notes": notes[:2000]}]}), "application/json")},
        )
        if r.status_code >= 400:
            raise PayPalError(r.status_code, r.text)
        return r.json() if r.content else {}

    # ---------- Transaction Search (reconciliation) ----------
    async def search_transactions(self, start: str, end: str, max_pages: int = 10) -> list[dict]:
        """All transactions between two ISO-8601 instants (PayPal allows at most 31 days per query)."""
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            res = await self.request(
                "GET", "/v1/reporting/transactions",
                params={"start_date": start, "end_date": end, "fields": "transaction_info", "page_size": 100, "page": page},
            )
            out.extend(res.get("transaction_details", []))
            if page >= int(res.get("total_pages") or 1):
                break
            page += 1
        return out

    # ---------- Webhooks ----------
    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool:
        if not self.s.paypal_webhook_id:
            return False
        h = {k.lower(): v for k, v in headers.items()}
        body = {
            "auth_algo": h.get("paypal-auth-algo"),
            "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"),
            "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"),
            "webhook_id": self.s.paypal_webhook_id,
            "webhook_event": event,
        }
        if not all(body.values()):
            return False
        res = await self.request("POST", "/v1/notifications/verify-webhook-signature", json=body)
        return res.get("verification_status") == "SUCCESS"
