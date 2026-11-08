"""Order lifecycle workflow: link sent -> paid -> kitchen -> ready -> crew payout.
If unpaid: reminder text (missed-call recovery) -> wait again -> expire.

Primary engine: Temporal (durable; survives API restarts; worker in app/worker.py).
Fallback: an in-process asyncio runner executing the same steps, so the money loop
still completes when Temporal is down.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

log = logging.getLogger("callpay.workflows")


@dataclass
class FlowTimings:
    payment_timeout_s: int
    reminder_wait_s: int
    fulfil_seconds: int


@dataclass
class Ops:
    """The workflow steps. Implemented by the API; Temporal activities reach them over HTTP."""

    status: Callable[[str], Awaitable[str]]
    fulfil: Callable[[str], Awaitable[None]]
    ready: Callable[[str], Awaitable[None]]
    crew_payout: Callable[[str], Awaitable[None]]
    remind: Callable[[str], Awaitable[None]]
    expire: Callable[[str], Awaitable[None]]


PAID = ("paid", "preparing", "ready")


async def run_local_flow(order_id: str, ops: Ops, t: FlowTimings, paid_event: asyncio.Event) -> None:
    async def wait_paid(timeout: int) -> bool:
        try:
            await asyncio.wait_for(paid_event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return await ops.status(order_id) in PAID

    if not await wait_paid(t.payment_timeout_s):
        await ops.remind(order_id)
        if not await wait_paid(t.reminder_wait_s):
            await ops.expire(order_id)
            return
    await ops.fulfil(order_id)
    await asyncio.sleep(t.fulfil_seconds)
    await ops.ready(order_id)
    await ops.crew_payout(order_id)


class FlowEngine:
    def __init__(self, address: str, task_queue: str, ops: Ops, timings: FlowTimings):
        self.address, self.task_queue, self.ops, self.t = address, task_queue, ops, timings
        self.client = None
        self.backend = "local"
        self._local: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}

    async def start(self) -> None:
        if not self.address:
            return
        try:
            from temporalio.client import Client

            self.client = await asyncio.wait_for(Client.connect(self.address), timeout=5)
            self.backend = "temporal"
            log.info("Workflow engine: temporal at %s", self.address)
        except Exception as e:  # noqa: BLE001
            log.warning("Temporal unavailable (%s); using in-process workflows", e)

    async def start_order(self, order_id: str) -> str:
        if self.client is not None:
            try:
                from .temporal_flow import OrderWorkflow

                await self.client.start_workflow(
                    OrderWorkflow.run,
                    args=[order_id, self.t.payment_timeout_s, self.t.reminder_wait_s, self.t.fulfil_seconds],
                    id=f"order-{order_id}", task_queue=self.task_queue,
                )
                return "temporal"
            except Exception as e:  # noqa: BLE001
                log.warning("Temporal start failed (%s); running order %s in-process", e, order_id)
        ev = asyncio.Event()
        task = asyncio.create_task(self._guard(order_id, ev))
        self._local[order_id] = (task, ev)
        return "local"

    async def _guard(self, order_id: str, ev: asyncio.Event) -> None:
        try:
            await run_local_flow(order_id, self.ops, self.t, ev)
        except Exception:  # noqa: BLE001
            log.exception("local workflow for %s failed", order_id)
        finally:
            self._local.pop(order_id, None)

    async def signal_paid(self, order_id: str) -> None:
        if order_id in self._local:
            self._local[order_id][1].set()
            return
        if self.client is not None:
            try:
                await self.client.get_workflow_handle(f"order-{order_id}").signal("paid")
            except Exception as e:  # noqa: BLE001
                log.warning("Temporal signal failed for %s (%s)", order_id, e)

    async def stop(self) -> None:
        tasks = [t for t, _ in self._local.values()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=5)
