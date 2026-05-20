# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Internal helpers shared across the SDKStats sub-package."""

from __future__ import annotations

import threading
from typing import Dict, Tuple

from microsoft.opentelemetry._sdkstats._constants import REQUEST_SUCCESS_NAME

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
_REQUESTS_MAP: Dict[str, Dict[Tuple[str, ...], float]] = {
    REQUEST_SUCCESS_NAME: {},
}


# Increment the counter for the given metric/key by the given value (default 1.0).
def _bump(metric: str, key: Tuple[str, ...], value: float = 1.0) -> None:
    with _REQUESTS_MAP_LOCK:
        bucket = _REQUESTS_MAP[metric]
        bucket[key] = bucket.get(key, 0) + value


def record_success(endpoint: str) -> None:
    _bump(REQUEST_SUCCESS_NAME, (endpoint,))


# Returns the counts accumulated since the last call, and resets the counters to zero.
def drain(metric: str) -> Dict[Tuple[str, ...], float]:
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
