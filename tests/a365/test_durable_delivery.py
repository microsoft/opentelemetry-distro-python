# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for durable delivery dispositions and the transmission gate."""

from __future__ import annotations

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    IdentityKey,
    TransmissionGate,
)


class FakeClock:
    """Callable monotonic clock used by gate tests."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_delivery_result_defaults_to_retryable_without_backoff() -> None:
    """DeliveryResult should model a retryable disposition with no delay."""
    result = DeliveryResult(DeliveryDisposition.RETRYABLE)

    assert result.disposition is DeliveryDisposition.RETRYABLE
    assert result.retry_after is None


def test_gate_isolates_identities() -> None:
    """A retryable failure should not block a different identity."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    first = IdentityKey("t1", "a1", None, False)
    second = IdentityKey("t2", "a2", None, False)

    gate.record_retryable_failure(first, retry_after=30)

    assert not gate.try_acquire(first)
    assert gate.try_acquire(second)


def test_gate_allows_only_one_half_open_probe() -> None:
    """Only one probe may be in flight when a gate opens."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=10)
    clock.advance(10)

    assert gate.try_acquire(key)
    assert not gate.try_acquire(key)


def test_explicit_retry_after_is_clamped_to_floor() -> None:
    """Retry-After values lower than 10 seconds should be raised to the floor."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=1)

    assert not gate.try_acquire(key)
    clock.advance(9.9)
    assert not gate.try_acquire(key)
    clock.advance(0.1)
    assert gate.try_acquire(key)


def test_explicit_retry_after_is_clamped_to_cap() -> None:
    """Retry-After values above one hour should be capped."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=7200)

    assert not gate.try_acquire(key)
    clock.advance(3599.9)
    assert not gate.try_acquire(key)
    clock.advance(0.1)
    assert gate.try_acquire(key)
