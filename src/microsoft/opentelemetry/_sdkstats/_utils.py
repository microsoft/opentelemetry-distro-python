# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Internal helpers shared across the SDKStats sub-package."""

from __future__ import annotations

import threading

from microsoft.opentelemetry._sdkstats._constants import REQUEST_SUCCESS_NAME

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
# Per-export success counts for telemetry exporters.  Exporters call
# ``record_success`` after each successful transmit; the
# ``SdkStatsMetrics`` callback drains the accumulated counts on each
# export interval.

__all__ = ["record_success", "drain", "reset_all"]


_REQUESTS_MAP_LOCK = threading.Lock()
_REQUESTS_MAP: dict[str, dict[tuple[str, ...], float]] = {
    REQUEST_SUCCESS_NAME: {},
}


# Increment the counter for the given metric/key by the given value (default 1.0).
def _bump(metric: str, key: tuple[str, ...], value: float = 1.0) -> None:
    with _REQUESTS_MAP_LOCK:
        bucket = _REQUESTS_MAP[metric]
        bucket[key] = bucket.get(key, 0) + value


def record_success(endpoint: str, host: str) -> None:
    _bump(REQUEST_SUCCESS_NAME, (endpoint, host))


# Returns the counts accumulated since the last call, and resets the counters to zero.
def drain(metric: str) -> dict[tuple[str, ...], float]:
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
