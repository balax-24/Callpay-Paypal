"""Policy engine for money leaving the business (payouts, later refunds).

auto     -> execute immediately
approval -> park in the approval queue until the owner decides
deny     -> never executed
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Decision:
    decision: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"decision": self.decision, "reasons": self.reasons}


def evaluate_payout(items: list[dict], *, auto_limit: Decimal, max_total: Decimal, max_item: Decimal) -> Decision:
    deny, review = [], []
    total = sum((Decimal(str(i["amount"])) for i in items), Decimal("0"))
    if not items:
        deny.append("no payout items")
    if any(Decimal(str(i["amount"])) <= 0 for i in items):
        deny.append("amounts must be positive")
    if total > max_total:
        deny.append(f"total {total:.2f} exceeds hard limit {max_total:.2f}")
    for i in items:
        if Decimal(str(i["amount"])) > max_item:
            deny.append(f"{i.get('name', i.get('email'))}: {Decimal(str(i['amount'])):.2f} exceeds per-person limit {max_item:.2f}")
    emails = [i["email"].lower() for i in items]
    if len(emails) != len(set(emails)):
        deny.append("same recipient listed twice")
    if deny:
        return Decision("deny", deny)
    if total > auto_limit:
        review.append(f"total {total:.2f} is above auto-approve limit {auto_limit:.2f}")
    return Decision("approval", review) if review else Decision("auto", ["within auto-approve limit"])


def evaluate_refund(amount: Decimal, order_total: Decimal, already_refunded: Decimal, *, auto_limit: Decimal) -> Decision:
    if amount <= 0:
        return Decision("deny", ["amount must be positive"])
    if amount + already_refunded > order_total:
        return Decision("deny", [f"refunds would exceed the order total {order_total:.2f}"])
    if amount > auto_limit:
        return Decision("approval", [f"{amount:.2f} is above refund auto-approve limit {auto_limit:.2f}"])
    return Decision("auto", ["within refund auto-approve limit"])
