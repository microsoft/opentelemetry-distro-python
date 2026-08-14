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


def test_healthy_acquire_does_not_create_gate_state() -> None:
    """Healthy sends should remain allocation-free until a failure occurs."""
    gate = TransmissionGate(clock=FakeClock(), random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    assert gate.try_acquire(key)
    assert gate.try_acquire(key)
    assert key not in gate._states  # type: ignore[attr-defined]


def test_gate_allows_only_one_half_open_probe() -> None:
    """Only one probe may be in flight when a gate opens."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=10)
    clock.advance(10)

    assert gate.try_acquire(key)
    assert not gate.try_acquire(key)


def test_positive_retry_after_is_honored_without_flooring() -> None:
    """Positive Retry-After values should keep their exact delay."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=1.5)

    assert not gate.try_acquire(key)
    clock.advance(1.49)
    assert not gate.try_acquire(key)
    clock.advance(0.01)
    assert gate.try_acquire(key)


def test_non_positive_retry_after_falls_back_to_jittered_backoff() -> None:
    """Retry-After values at or below zero should use exponential-jitter backoff."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    gate.record_retryable_failure(key, retry_after=None)
    clock.advance(10)
    assert gate.try_acquire(key)

    gate.record_retryable_failure(key, retry_after=0)

    assert not gate.try_acquire(key)
    clock.advance(14.99)
    assert not gate.try_acquire(key)
    clock.advance(0.01)
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


# ---------------------------------------------------------------------------
# Regression tests: backoff overflow at high failure counts (exponent ≥ 1024)
# ---------------------------------------------------------------------------


def _drive_failure_count(gate: TransmissionGate, key: IdentityKey, n: int) -> None:
    """Record *n* consecutive retryable failures without a retry_after hint."""
    for _ in range(n):
        gate.record_retryable_failure(key, retry_after=None)


def test_record_retryable_failure_never_raises_beyond_exponent_1024() -> None:
    """Calling record_retryable_failure 1025+ times must never raise OverflowError.

    Previously ``2.0 ** failure_count`` would overflow once failure_count
    reached ~1024, producing an OverflowError (Python floats map to C doubles).
    The fix must clamp the exponent so the calculation stays finite.
    """
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 1.0)
    key = IdentityKey("t1", "a1", None, False)

    # Drive failure_count well past the problematic threshold and verify no
    # exception is raised and no busy-loop / infinite delay results.
    _drive_failure_count(gate, key, 1025)


def test_backoff_stays_capped_at_3600_seconds_beyond_exponent_1024() -> None:
    """Delay must never exceed 3600 s regardless of failure count."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 1.0)
    key = IdentityKey("t1", "a1", None, False)

    _drive_failure_count(gate, key, 1025)

    # Check that the gate opens exactly at 3600 s (worst-case random fraction = 1.0).
    clock.advance(3599.9)
    assert not gate.try_acquire(key)
    clock.advance(0.1)
    assert gate.try_acquire(key)


def test_half_open_behavior_preserved_after_high_failure_count() -> None:
    """Only one probe is allowed in the half-open window after >1024 failures."""
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 1.0)
    key = IdentityKey("t1", "a1", None, False)

    _drive_failure_count(gate, key, 2000)

    # Advance past the cap window.
    clock.advance(3600.0)

    # Exactly one probe must be allowed (half-open), then the gate must hold.
    assert gate.try_acquire(key), "first probe should be granted"
    assert not gate.try_acquire(key), "second probe must be refused while first is in flight"


def test_failure_count_does_not_grow_unbounded() -> None:
    """failure_count must be saturated at a finite value; it must not grow to
    an arbitrary integer that would cause overflow on subsequent calls."""
    from microsoft.opentelemetry.a365.core.exporters.durable_delivery import _GateState  # noqa: PLC0415

    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)

    _drive_failure_count(gate, key, 5000)

    state: _GateState = gate._states[key]  # type: ignore[attr-defined]
    # The clamped value must be at most the threshold that makes backoff hit cap.
    # Derived from: floor * 2^n >= cap  =>  n = ceil(log2(cap / floor)) = 9
    import math  # noqa: PLC0415
    from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (  # noqa: PLC0415
        _RETRY_AFTER_CAP_SECONDS,
        _RETRY_AFTER_FLOOR_SECONDS,
    )
    max_useful_exponent = math.ceil(math.log2(_RETRY_AFTER_CAP_SECONDS / _RETRY_AFTER_FLOOR_SECONDS))
    assert state.failure_count <= max_useful_exponent, (
        f"failure_count={state.failure_count} exceeds max useful exponent {max_useful_exponent}"
    )
