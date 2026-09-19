"""
Tests for the RPC rate limiter (arth_raksha/backend/wallet_reader.py) —
added after a real hyperactive wallet's risk check made dozens of rapid
calls against the shared free RPC (see risk_engine.MAX_ML_LOOKUPS_PER_REQUEST,
also added from that same finding).

Uses a fake, monkeypatched clock rather than real sleeping — the first
version of this test used real `time.sleep`/`time.monotonic` with small
(tens-of-ms) intervals and was genuinely flaky under load (scheduler
jitter routinely exceeded the margins when the full suite ran together,
though it always passed in isolation). A fake clock makes the assertions
exact instead of "probably long enough."
"""
from __future__ import annotations

from arth_raksha.backend import wallet_reader as wr
from arth_raksha.backend.wallet_reader import RateLimiter


class _FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds: float):
        self.sleep_calls.append(seconds)
        self.now += seconds  # simulate time actually passing while "asleep"

    def advance(self, seconds: float):
        self.now += seconds


def _patched_limiter(monkeypatch, min_interval=0.1):
    clock = _FakeClock()
    monkeypatch.setattr(wr.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(wr.time, "sleep", clock.sleep)
    return RateLimiter(min_interval_seconds=min_interval), clock


def test_first_call_never_waits(monkeypatch):
    limiter, clock = _patched_limiter(monkeypatch)
    limiter.wait()
    assert clock.sleep_calls == []


def test_call_before_interval_elapsed_waits_exactly_the_remainder(monkeypatch):
    limiter, clock = _patched_limiter(monkeypatch, min_interval=0.1)
    limiter.wait()          # t=0, no wait
    clock.advance(0.03)     # only 30ms have "passed"
    limiter.wait()          # needs to wait the remaining 70ms
    assert clock.sleep_calls == [0.1 - 0.03]


def test_call_after_interval_has_elapsed_does_not_wait(monkeypatch):
    limiter, clock = _patched_limiter(monkeypatch, min_interval=0.1)
    limiter.wait()
    clock.advance(0.2)  # well past the interval
    limiter.wait()
    assert clock.sleep_calls == []


def test_rapid_calls_each_wait_for_the_remaining_gap(monkeypatch):
    limiter, clock = _patched_limiter(monkeypatch, min_interval=0.05)
    limiter.wait()  # no wait
    limiter.wait()  # waits 0.05 (clock auto-advances by that much during the simulated sleep)
    limiter.wait()  # waits 0.05 again
    assert clock.sleep_calls == [0.05, 0.05]
