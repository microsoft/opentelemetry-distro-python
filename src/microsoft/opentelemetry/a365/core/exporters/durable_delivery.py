# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Durable delivery dispositions and per-identity transmission gating."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock

_RETRY_AFTER_FLOOR_SECONDS = 10.0
_RETRY_AFTER_CAP_SECONDS = 3600.0


class DeliveryDisposition(Enum):
    """The outcome of a delivery attempt."""

    DELIVERED = "delivered"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class DeliveryResult:
    """Delivery outcome and optional retry delay."""

    disposition: DeliveryDisposition
    retry_after: float | None = None


@dataclass(frozen=True)
class IdentityKey:
    """Identity tuple used to isolate durable delivery state."""

    tenant_id: str
    agent_id: str
    agentic_user_id: str | None
    use_s2s_endpoint: bool


@dataclass
class _GateState:
    """Mutable gate state tracked per identity."""

    blocked_until: float = 0.0
    probe_acquired: bool = False
    failure_count: int = 0


class TransmissionGate:
    """Gate retries per identity and allows only one half-open probe."""

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        random_fn: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._random_fn = random_fn or random.random
        self._lock = RLock()
        self._states: dict[IdentityKey, _GateState] = {}

    def try_acquire(self, key: IdentityKey) -> bool:
        """Acquire the probe token for an identity if it is available."""
        with self._lock:
            state = self._states.get(key)
            if state is None:
                self._states[key] = _GateState(probe_acquired=True)
                return True

            if self._clock() < state.blocked_until:
                return False
            if state.probe_acquired:
                return False

            state.probe_acquired = True
            return True

    def record_success(self, key: IdentityKey) -> None:
        """Reset durable delivery state after a successful attempt."""
        with self._lock:
            self._states.pop(key, None)

    def record_retryable_failure(self, key: IdentityKey, retry_after: float | None) -> None:
        """Block the identity until the retry window expires."""
        with self._lock:
            state = self._states.setdefault(key, _GateState())
            delay = self._resolve_retry_delay(state.failure_count, retry_after)
            state.failure_count += 1
            state.blocked_until = self._clock() + delay
            state.probe_acquired = False

    def release_probe(self, key: IdentityKey) -> None:
        """Release an acquired probe token without changing the retry window."""
        with self._lock:
            state = self._states.get(key)
            if state is not None:
                state.probe_acquired = False

    def _resolve_retry_delay(self, failure_count: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return self._clamp_retry_after(retry_after)
        return self._full_jitter_backoff(failure_count)

    def _full_jitter_backoff(self, failure_count: int) -> float:
        window = _RETRY_AFTER_FLOOR_SECONDS * (2.0**failure_count)
        window = min(_RETRY_AFTER_CAP_SECONDS, window)
        if window <= _RETRY_AFTER_FLOOR_SECONDS:
            return _RETRY_AFTER_FLOOR_SECONDS

        fraction = self._random_fraction()
        return _RETRY_AFTER_FLOOR_SECONDS + fraction * (window - _RETRY_AFTER_FLOOR_SECONDS)

    def _random_fraction(self) -> float:
        fraction = self._random_fn()
        if fraction < 0.0:
            return 0.0
        if fraction > 1.0:
            return 1.0
        return fraction

    def _clamp_retry_after(self, retry_after: float) -> float:
        if retry_after < _RETRY_AFTER_FLOOR_SECONDS:
            return _RETRY_AFTER_FLOOR_SECONDS
        if retry_after > _RETRY_AFTER_CAP_SECONDS:
            return _RETRY_AFTER_CAP_SECONDS
        return retry_after


__all__ = [
    "DeliveryDisposition",
    "DeliveryResult",
    "IdentityKey",
    "TransmissionGate",
]
