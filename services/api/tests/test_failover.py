import pytest

from app.providers.breaker import CircuitBreaker, State
from app.providers.chain import AllProvidersFailed, FallbackChain


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Fake:
    def __init__(self, name, fail=False, configured=True):
        self.name, self.fail, self._configured, self.calls = name, fail, configured, 0

    def configured(self):
        return self._configured

    async def run(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} down")
        return self.name


def test_breaker_opens_and_recovers():
    clock = FakeClock()
    b = CircuitBreaker(failure_threshold=3, window_s=30, cooldown_s=60, clock=clock)
    for _ in range(3):
        b.record_failure("x")
    assert b.state == State.OPEN and not b.allow()
    clock.t = 61
    assert b.state == State.HALF_OPEN and b.allow()
    b.record_success()
    assert b.state == State.CLOSED


async def test_chain_falls_back_and_reports():
    events = []
    a, b = Fake("a", fail=True), Fake("b")
    chain = FallbackChain("llm", [a, b], on_failover=events.append)
    result, used = await chain.call(lambda p: p.run())
    assert (result, used) == ("b", "b")
    assert events[0].from_provider == "a" and events[0].to_provider == "b"


async def test_chain_skips_unconfigured_and_killed():
    a, b, c = Fake("a", configured=False), Fake("b"), Fake("c")
    chain = FallbackChain("llm", [a, b, c])
    chain.kill("b")
    _, used = await chain.call(lambda p: p.run())
    assert used == "c" and a.calls == 0 and b.calls == 0
    chain.revive("b")
    _, used = await chain.call(lambda p: p.run())
    assert used == "b"


async def test_chain_all_fail():
    chain = FallbackChain("llm", [Fake("a", fail=True), Fake("b", fail=True)])
    with pytest.raises(AllProvidersFailed) as e:
        await chain.call(lambda p: p.run())
    assert set(e.value.errors) == {"a", "b"}
