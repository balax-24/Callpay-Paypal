"""Circuit breaker: skip a provider after repeated failures, retry it later."""

import time
from enum import Enum


class State(str, Enum):
    CLOSED = "closed"  # healthy, calls go through
    OPEN = "open"  # failing, calls skipped
    HALF_OPEN = "half_open"  # cooldown over, one trial call allowed


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        window_s: float = 30.0,
        cooldown_s: float = 60.0,
        clock=time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._failures: list[float] = []
        self._opened_at: float | None = None
        self.last_error: str | None = None

    @property
    def state(self) -> State:
        if self._opened_at is None:
            return State.CLOSED
        if self._clock() - self._opened_at >= self.cooldown_s:
            return State.HALF_OPEN
        return State.OPEN

    def allow(self) -> bool:
        return self.state != State.OPEN

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None
        self.last_error = None

    def record_failure(self, error: str = "") -> None:
        now = self._clock()
        self.last_error = error[:300]
        if self.state == State.HALF_OPEN:
            self._opened_at = now  # trial failed, reopen
            return
        self._failures = [t for t in self._failures if now - t < self.window_s]
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._opened_at = now

    def force_open(self) -> None:
        """Used by the demo 'kill switch'."""
        self._opened_at = self._clock()
        self._failures.clear()
        self.last_error = "manually disabled"

    def reset(self) -> None:
        self.record_success()
