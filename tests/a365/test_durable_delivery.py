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


def test_release_probe_allows_another_probe_to_be_acquired() -> None:
    """Releasing an in-flight probe should let a fresh probe be acquired."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=10)
    clock.advance(10)

    assert gate.try_acquire(key)
    # Only one probe may be in flight, so a second acquire is refused.
    assert not gate.try_acquire(key)

    gate.release_probe(key)

    # After releasing the probe (without changing the retry window) another
    # probe may be acquired.
    assert gate.try_acquire(key)


def test_release_probe_is_noop_for_unknown_identity() -> None:
    """Releasing a probe for an unseen identity must not create state or raise."""
    gate = TransmissionGate(clock=FakeClock(), random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.release_probe(key)

    # The identity has never failed, so a probe should still be acquirable.
    assert gate.try_acquire(key)


def test_release_probe_preserves_retry_window() -> None:
    """release_probe must not shorten the active backoff window."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=30)
    gate.release_probe(key)

    # Still blocked because the window has not elapsed.
    assert not gate.try_acquire(key)
    clock.advance(30)
    assert gate.try_acquire(key)


def test_record_success_resets_backoff_immediately() -> None:
    """A success should clear the block so the identity can send at once."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=3600)
    assert not gate.try_acquire(key)

    gate.record_success(key)

    # State is fully reset, so a send may proceed without waiting the window.
    assert gate.try_acquire(key)


def test_record_success_resets_failure_count() -> None:
    """After success, the next failure uses the base backoff, not escalated."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 1.0)
    key = IdentityKey("t1", "a1", None, False)

    # Escalate the failure count several times.
    for _ in range(4):
        gate.record_retryable_failure(key, retry_after=None)

    gate.record_success(key)

    # A fresh failure after success blocks only for the base floor window,
    # proving failure_count was reset to zero.
    gate.record_retryable_failure(key, retry_after=None)
    clock.advance(9.999)
    assert not gate.try_acquire(key)
    clock.advance(0.001)
    assert gate.try_acquire(key)


def test_record_success_for_unknown_identity_is_noop() -> None:
    """Recording success for an unseen identity must not raise or block."""
    gate = TransmissionGate(clock=FakeClock(), random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_success(key)

    assert gate.try_acquire(key)
