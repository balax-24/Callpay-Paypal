"""Temporal definition of the order workflow. Activities call the API's internal endpoints,
so the worker can run on any host and the API stays the single owner of the database."""

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import os

    import httpx

API = os.environ.get("API_INTERNAL_URL", "http://api:8000")
INTERNAL_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=30), maximum_attempts=20)


async def _post(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{API}{path}", headers={"X-CallPay-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {})
        r.raise_for_status()
        return r.json()


@activity.defn
async def order_status(order_id: str) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API}/orders/{order_id}")
        r.raise_for_status()
        return r.json()["status"]


@activity.defn
async def flow_step(order_id: str, step: str) -> None:
    await _post(f"/internal/orders/{order_id}/{step}")


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self.paid = False

    @workflow.signal(name="paid")
    def paid_signal(self) -> None:
        self.paid = True

    @workflow.run
    async def run(self, order_id: str, payment_timeout_s: int, reminder_wait_s: int, fulfil_seconds: int) -> str:
        opts = dict(start_to_close_timeout=timedelta(seconds=60), retry_policy=RETRY)

        async def wait_paid(seconds: int) -> bool:
            try:
                await workflow.wait_condition(lambda: self.paid, timeout=timedelta(seconds=seconds))
                return True
            except TimeoutError:
                status = await workflow.execute_activity(order_status, order_id, **opts)
                return status in ("paid", "preparing", "ready")

        if not await wait_paid(payment_timeout_s):
            await workflow.execute_activity(flow_step, args=[order_id, "remind"], **opts)
            if not await wait_paid(reminder_wait_s):
                await workflow.execute_activity(flow_step, args=[order_id, "expire"], **opts)
                return "expired"
        await workflow.execute_activity(flow_step, args=[order_id, "fulfil"], **opts)
        await workflow.sleep(timedelta(seconds=fulfil_seconds))
        await workflow.execute_activity(flow_step, args=[order_id, "ready"], **opts)
        await workflow.execute_activity(flow_step, args=[order_id, "crew_payout"], **opts)
        return "completed"

