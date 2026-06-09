# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Internal helpers shared across the SDKStats sub-package."""

from __future__ import annotations

import threading
from typing import Any, Dict, Tuple

from microsoft.opentelemetry._sdkstats._constants import (
    REQUEST_DURATION_NAME,
    REQUEST_EXCEPTION_NAME,
    REQUEST_FAILURE_NAME,
    REQUEST_RETRY_NAME,
    REQUEST_SUCCESS_NAME,
    REQUEST_THROTTLE_NAME,
)

# ===========================================================================
# Global state helpers (Azure Monitor exporter statsbeat bridge)
# ===========================================================================
#
# These helpers OR distro-side feature/instrumentation bits into the
# Azure Monitor exporter's statsbeat global state so the exporter emits
# accurate feature/instrumentation statsbeat metrics on our behalf.


def update_global_state_feature_bits(feature_bits: int) -> None:
    """OR ``feature_bits`` into the exporter statsbeat feature mask."""
    from azure.monitor.opentelemetry.exporter.statsbeat._statsbeat_metrics import (  # type: ignore[import-not-found]
        _StatsbeatMetrics,
    )

    current = _StatsbeatMetrics._FEATURE_ATTRIBUTES.get("feature") or 0
    _StatsbeatMetrics._FEATURE_ATTRIBUTES["feature"] = current | int(feature_bits)


def update_global_state_instrumentation_bits(instrumentation_bits: int) -> None:
    """OR ``instrumentation_bits`` into the exporter instrumentation mask."""
    import azure.monitor.opentelemetry.exporter._utils as _exporter_utils  # type: ignore[import-not-found]

    with _exporter_utils._INSTRUMENTATIONS_BIT_MASK_LOCK:
        _exporter_utils._INSTRUMENTATIONS_BIT_MASK |= int(instrumentation_bits)


# ===========================================================================
# Network sdkstats
# ===========================================================================
#
# Per-export counters and per-request duration accumulators for telemetry
# exporters.  Exporters call the ``record_*`` helpers; the observable
# callbacks in ``_network_metrics`` drain the accumulated state on each
# export interval.

__all__ = [
    "record_success",
    "record_duration",
    "record_failure",
    "record_retry",
    "record_throttle",
    "record_exception",
    "drain",
    "reset_all",
]


_REQUESTS_MAP_LOCK = threading.Lock()
_REQUESTS_MAP: Dict[str, Dict[Tuple[Any, ...], Any]] = {
    REQUEST_SUCCESS_NAME: {},
    REQUEST_DURATION_NAME: {},
    REQUEST_FAILURE_NAME: {},
    REQUEST_RETRY_NAME: {},
    REQUEST_THROTTLE_NAME: {},
    REQUEST_EXCEPTION_NAME: {},
}


# Increment the counter for the given metric/key by the given value (default 1.0).
def _bump(metric: str, key: Tuple[Any, ...], value: float = 1.0) -> None:
    with _REQUESTS_MAP_LOCK:
        bucket = _REQUESTS_MAP[metric]
        bucket[key] = bucket.get(key, 0) + value


def record_success(endpoint: str, host: str) -> None:
    _bump(REQUEST_SUCCESS_NAME, (endpoint, host))


def record_duration(endpoint: str, host: str, duration_seconds: float) -> None:
    """Record one request-duration sample (in seconds) for averaging.

    Stored as a running (sum_seconds, count) tuple per (endpoint, host) so
    the observable callback can compute an interval average without
    retaining individual samples.
    """
    key = (endpoint, host)
    with _REQUESTS_MAP_LOCK:
        bucket = _REQUESTS_MAP[REQUEST_DURATION_NAME]
        existing = bucket.get(key, (0.0, 0))
        bucket[key] = (existing[0] + float(duration_seconds), existing[1] + 1)


def record_failure(endpoint: str, host: str, status_code: int) -> None:
    _bump(REQUEST_FAILURE_NAME, (endpoint, host, int(status_code)))


def record_retry(endpoint: str, host: str, status_code: int) -> None:
    _bump(REQUEST_RETRY_NAME, (endpoint, host, int(status_code)))


def record_throttle(endpoint: str, host: str, status_code: int) -> None:
    _bump(REQUEST_THROTTLE_NAME, (endpoint, host, int(status_code)))


def record_exception(endpoint: str, host: str, exception_type: str) -> None:
    _bump(REQUEST_EXCEPTION_NAME, (endpoint, host, str(exception_type)))


# Returns the counts accumulated since the last call, and resets the counters to zero.
def drain(metric: str) -> Dict[Tuple[Any, ...], Any]:
    with _REQUESTS_MAP_LOCK:
        bucket = _REQUESTS_MAP[metric]
        snapshot = dict(bucket)
        bucket.clear()
        return snapshot


def reset_all() -> None:
    """Clear all counters.  Intended for tests."""
    with _REQUESTS_MAP_LOCK:
        for bucket in _REQUESTS_MAP.values():
            bucket.clear()
