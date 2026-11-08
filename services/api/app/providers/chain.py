"""Generic fallback chain: try providers in priority order until one succeeds."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar

from .breaker import CircuitBreaker

log = logging.getLogger("callpay.providers")


class Provider(Protocol):
    name: str

    def configured(self) -> bool: ...


P = TypeVar("P", bound=Provider)
R = TypeVar("R")


class AllProvidersFailed(RuntimeError):
    def __init__(self, layer: str, errors: dict[str, str]):
        super().__init__(f"all {layer} providers failed: {errors}")
        self.errors = errors


@dataclass
class FailoverEvent:
    layer: str
    from_provider: str
    to_provider: str | None
    reason: str
    ts: float = field(default_factory=time.time)


class FallbackChain(Generic[P]):
    def __init__(
        self,
        layer: str,
        providers: list[P],
        timeout_s: float = 20.0,
        on_failover: Callable[[FailoverEvent], None] | None = None,
    ):
        self.layer = layer
        self.providers = providers
        self.timeout_s = timeout_s
        self.breakers = {p.name: CircuitBreaker() for p in providers}
        self.on_failover = on_failover
        self.last_used: str | None = None

    def active(self) -> list[P]:
        return [p for p in self.providers if p.configured() and self.breakers[p.name].allow()]

    async def call(self, fn: Callable[[P], Awaitable[R]]) -> tuple[R, str]:
        errors: dict[str, str] = {}
        candidates = self.active()
        for i, p in enumerate(candidates):
            br = self.breakers[p.name]
            try:
                result = await asyncio.wait_for(fn(p), timeout=self.timeout_s)
            except Exception as e:  # noqa: BLE001 - any failure triggers failover
                reason = f"{type(e).__name__}: {e}"
                errors[p.name] = reason
                br.record_failure(reason)
                nxt = candidates[i + 1].name if i + 1 < len(candidates) else None
                log.warning("%s provider %s failed (%s); next=%s", self.layer, p.name, reason, nxt)
                if self.on_failover:
                    self.on_failover(FailoverEvent(self.layer, p.name, nxt, reason))
                continue
            br.record_success()
            self.last_used = p.name
            return result, p.name
        raise AllProvidersFailed(self.layer, errors or {"*": "no configured provider available"})

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "provider": p.name,
                "configured": p.configured(),
                "state": self.breakers[p.name].state.value,
                "last_error": self.breakers[p.name].last_error,
                "primary": i == 0,
                "last_used": p.name == self.last_used,
            }
            for i, p in enumerate(self.providers)
        ]

    def kill(self, name: str) -> None:
        self.breakers[name].force_open()

    def revive(self, name: str) -> None:
        self.breakers[name].reset()
