# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Distro-owned network SDKStats gauges.

The upstream statsbeat metrics only count requests sent to the Breeze
endpoint (the Azure Monitor exporter's destination).  This distro also
ships OTLP and Agent365 exporters, whose per-export success counters
live in the distro's own ``_REQUESTS_MAP``.  This module registers an
observable gauge on the upstream ``StatsbeatManager``'s ``MeterProvider``
so those counters are exported on the same statsbeat pipeline.
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable, List

from opentelemetry.metrics import CallbackOptions, Observation

from microsoft.opentelemetry._sdkstats._utils import (
    REQUEST_SUCCESS_NAME,
    drain,
)

from microsoft.opentelemetry._version import VERSION

try:  # Upstream is an optional dependency for non-AzMon consumers.
    from azure.monitor.opentelemetry.exporter.statsbeat._statsbeat_metrics import (
        _StatsbeatMetrics,
    )
except ImportError:  # pragma: no cover
    _StatsbeatMetrics = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_REGISTER_LOCK = threading.Lock()
_registered = False


def _get_common_attributes() -> dict:
    if _StatsbeatMetrics is None:
        return {}
    return _StatsbeatMetrics._COMMON_ATTRIBUTES  # pylint: disable=protected-access


def _observe_request_success_count(options: CallbackOptions) -> Iterable[Observation]:
    """Drain the per-endpoint success counts and emit one observation each."""
    common = _get_common_attributes()

    observations: List[Observation] = []
   
    for key, value in drain(REQUEST_SUCCESS_NAME).items():
        attributes = dict(common)
        attributes["version"] = VERSION
        attributes["endpoint"] = key[0]
        attributes["host"] = key[1]
        attributes["statusCode"] = 200
        observations.append(Observation(value, attributes))
    return observations


def register_network_gauges() -> bool:
    """Attach distro network-stats callbacks to upstream's gauges.

    The distro emits per-endpoint ``Request_Success_Count`` observation
    via the upstream statsbeat pipeline.  We cannot create separate gauges 
    with the same names because the stats backend identifies metric streams by
    InstrumentationScope, and rows from an unknown scope are silently
    dropped.  Instead we append our callbacks to the already-registered
    upstream ``_success_count`` observable gauges
    so our observations are emitted on the exact same instrument/scope
    as upstream's breeze rows.

    Idempotent — subsequent calls are no-ops.  Returns ``True`` on the
    call that performs registration, ``False`` if registration was
    skipped (already registered, upstream unavailable, or upstream
    hasn't created the gauges yet).
    """
    global _registered  # pylint: disable=global-statement

    with _REGISTER_LOCK:
        if _registered:
            return False

        try:
            from azure.monitor.opentelemetry.exporter.statsbeat._manager import (
                StatsbeatManager,
            )
        except ImportError:
            logger.debug("Upstream statsbeat unavailable; skipping network gauges.")
            return False

        manager = StatsbeatManager()
        meter_provider = manager._meter_provider  # pylint: disable=protected-access
        metrics = manager._metrics  # pylint: disable=protected-access
        if meter_provider is None or metrics is None:
            logger.info("StatsbeatManager not initialised; skipping network gauges.")
            return False

        attached: List[str] = []
        for gauge_attr, callback in (
            ("_success_count", _observe_request_success_count),
        ):
            gauge = getattr(metrics, gauge_attr, None)
            if gauge is None:
                logger.info("Upstream %s gauge not yet created; skipping.", gauge_attr)
                continue
            try:
                gauge._callbacks.append(callback)  # pylint: disable=protected-access
            except AttributeError:
                logger.warning(
                    "Upstream %s gauge has no _callbacks list; cannot attach.", gauge_attr,
                )
                continue
            attached.append(gauge_attr)

        if not attached:
            return False

        logger.info(
            "distro callbacks attached to upstream %s on MeterProvider id=%s",
            attached, id(meter_provider),
        )
        _registered = True
        return True


def _reset_for_tests() -> None:
    """Reset the module-level registration guard.  Test-only."""
    global _registered  # pylint: disable=global-statement
    with _REGISTER_LOCK:
        _registered = False
