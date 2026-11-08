"""Temporal worker: `python -m app.worker`. Retries the connection until Temporal is up."""

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .temporal_flow import OrderWorkflow, flow_step, order_status

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("callpay.worker")


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
    queue = os.environ.get("TEMPORAL_TASK_QUEUE", "callpay")
    while True:
        try:
            client = await Client.connect(address)
            break
        except Exception as e:  # noqa: BLE001
            log.warning("waiting for Temporal at %s (%s)", address, e)
            await asyncio.sleep(5)
    log.info("worker polling task queue %s", queue)
    await Worker(client, task_queue=queue, workflows=[OrderWorkflow], activities=[flow_step, order_status]).run()


if __name__ == "__main__":
    asyncio.run(main())
