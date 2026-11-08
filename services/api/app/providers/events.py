"""Event bus: Kafka primary, in-process fallback. Publishing never blocks the money flow."""

import asyncio
import json
import logging
from collections import deque
from typing import Any

log = logging.getLogger("callpay.events")
ENVELOPE_TOPIC = "callpay.events"


class EventBus:
    def __init__(self, bootstrap: str | None):
        self.bootstrap = bootstrap
        self._producer = None
        self.backend = "memory"
        self.recent: deque[dict[str, Any]] = deque(maxlen=500)
        self._subscribers: set[asyncio.Queue] = set()
        self._retry_task: asyncio.Task | None = None
        self.hooks: list = []  # async fn(topic, payload, backend)

    async def start(self) -> None:
        """Try Kafka now; if it isn't up yet, keep retrying in the background."""
        if not self.bootstrap:
            return
        if not await self._connect():
            self._retry_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        while self._producer is None:
            await asyncio.sleep(10)
            if await self._connect():
                log.info("Kafka connected; event bus switched back to kafka")

    async def _connect(self) -> bool:
        producer = None
        try:
            from aiokafka import AIOKafkaProducer

            producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap,
                value_serializer=lambda v: json.dumps(v, default=str).encode(),
                request_timeout_ms=3000,
            )
            await asyncio.wait_for(producer.start(), timeout=5)
            self._producer = producer
            self.backend = "kafka"
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Kafka unavailable (%s); using in-memory event bus", e)
            if producer is not None:
                try:
                    await producer.stop()
                except Exception:  # noqa: BLE001
                    pass
            return False

    async def stop(self) -> None:
        if self._retry_task:
            self._retry_task.cancel()
        if self._producer:
            await self._producer.stop()

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        import time

        event = {"topic": topic, "ts": int(time.time() * 1000), **payload}
        self.recent.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        for hook in self.hooks:
            try:
                await hook(topic, payload, self.backend)
            except Exception as e:  # noqa: BLE001
                log.warning("event hook failed: %s", e)
        if self._producer:
            try:
                await self._producer.send_and_wait(topic, payload)
                # envelope stream consumed by ClickHouse (Kafka engine) and Flink
                await self._producer.send_and_wait(ENVELOPE_TOPIC, event)
            except Exception as e:  # noqa: BLE001
                log.warning("Kafka publish failed (%s); switching to in-memory", e)
                self._producer = None
                self.backend = "memory"
                self._retry_task = asyncio.create_task(self._reconnect_loop())

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)
