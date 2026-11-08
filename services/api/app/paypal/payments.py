"""Payment collection with fallback: PayPal Orders checkout link -> PayPal Invoice pay link."""

from dataclasses import dataclass
from decimal import Decimal

from ..providers.chain import FallbackChain
from .client import PayPalClient


@dataclass
class PaymentRequest:
    reference_id: str
    amount: Decimal
    currency: str
    description: str
    items: list[dict]


@dataclass
class PaymentLink:
    method: str
    paypal_ref: str
    url: str


class OrdersMethod:
    name = "orders"

    def __init__(self, pp: PayPalClient, app_url: str):
        self.pp, self.app_url = pp, app_url

    def configured(self) -> bool:
        return self.pp.configured()

    async def create(self, req: PaymentRequest) -> PaymentLink:
        order = await self.pp.create_order(
            reference_id=req.reference_id,
            amount=req.amount,
            currency=req.currency,
            description=req.description,
            items=req.items,
            return_url=f"{self.app_url}/paypal/return?ref={req.reference_id}",
            cancel_url=f"{self.app_url}/paypal/cancel?ref={req.reference_id}",
        )
        url = PayPalClient.approval_link(order)
        if not url:
            raise RuntimeError("PayPal order has no approval link")
        return PaymentLink("orders", order["id"], url)


class InvoiceMethod:
    name = "invoice"

    def __init__(self, pp: PayPalClient):
        self.pp = pp

    def configured(self) -> bool:
        return self.pp.configured()

    async def create(self, req: PaymentRequest) -> PaymentLink:
        inv = await self.pp.create_and_send_invoice(
            reference_id=req.reference_id, currency=req.currency, items=req.items, note=req.description
        )
        if not inv.get("pay_link"):
            raise RuntimeError("PayPal invoice has no pay link")
        return PaymentLink("invoice", inv["id"], inv["pay_link"])


def build_payment_chain(pp: PayPalClient, app_url: str, on_failover=None) -> FallbackChain:
    return FallbackChain(
        "payments", [OrdersMethod(pp, app_url), InvoiceMethod(pp)], timeout_s=25.0, on_failover=on_failover
    )
