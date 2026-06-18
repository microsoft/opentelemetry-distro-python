# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Distro-owned network SDKStats observations.

The upstream statsbeat metrics only count requests sent to the Breeze
endpoint. This distro also ships OTLP and Agent365 exporters whose
per-export counters live in the distro's own ``_REQUESTS_MAP``. We
contribute extra rows to the upstream ``Request_Success_Count`` metric
via ``add_metric_callback`` so the backend treats them as part of the
same metric stream (same name + InstrumentationScope).
"""

from __future__ import annotations

import logging
from typing import Iterable, List

from opentelemetry.metrics import CallbackOptions, Observation

from microsoft.opentelemetry._sdkstats._utils import (
    REQUEST_DURATION_NAME,
    REQUEST_EXCEPTION_NAME,
    REQUEST_FAILURE_NAME,
    REQUEST_RETRY_NAME,
    REQUEST_SUCCESS_NAME,
    REQUEST_THROTTLE_NAME,
    drain,
)

try:
    from azure.monitor.opentelemetry.exporter._constants import (
        _REQ_DURATION_NAME,
        _REQ_EXCEPTION_NAME,
        _REQ_FAILURE_NAME,
        _REQ_RETRY_NAME,
        _REQ_SUCCESS_NAME,
        _REQ_THROTTLE_NAME,
    )
    from azure.monitor.opentelemetry.exporter.statsbeat._statsbeat_metrics import (
        _StatsbeatMetrics,
    )
except ImportError:  # pragma: no cover
    _StatsbeatMetrics = None  # type: ignore[assignment,misc]

from microsoft.opentelemetry._version import VERSION

logger = logging.getLogger(__name__)


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


def _observe_request_duration(options: CallbackOptions) -> Iterable[Observation]:
    """Drain accumulated (sum_seconds, count) per (endpoint, host) and
    emit the interval *average* duration in milliseconds — matches
    upstream's ``Request_Duration`` semantics."""
    common = _get_common_attributes()

    observations: List[Observation] = []
    for key, value in drain(REQUEST_DURATION_NAME).items():
        total_seconds, count = value
        if count <= 0:
            continue
        avg_ms = (total_seconds / count) * 1000.0
        attributes = dict(common)
        attributes["version"] = VERSION
        attributes["endpoint"] = key[0]
        attributes["host"] = key[1]
        observations.append(Observation(avg_ms, attributes))
    return observations


def _observe_request_failure_count(options: CallbackOptions) -> Iterable[Observation]:
    """Drain the per-endpoint failure counts and emit one observation each."""
    common = _get_common_attributes()

    observations: List[Observation] = []
    for key, value in drain(REQUEST_FAILURE_NAME).items():
        attributes = dict(common)
        attributes["version"] = VERSION
        attributes["endpoint"] = key[0]
        attributes["host"] = key[1]
        attributes["statusCode"] = key[2]
        observations.append(Observation(value, attributes))
    return observations


def _observe_request_retry_count(options: CallbackOptions) -> Iterable[Observation]:
    """Drain the per-endpoint retry counts and emit one observation each."""
    common = _get_common_attributes()

    observations: List[Observation] = []
    for key, value in drain(REQUEST_RETRY_NAME).items():
        attributes = dict(common)
        attributes["version"] = VERSION
        attributes["endpoint"] = key[0]
        attributes["host"] = key[1]
        attributes["statusCode"] = key[2]
        observations.append(Observation(value, attributes))
    return observations


def _observe_request_throttle_count(options: CallbackOptions) -> Iterable[Observation]:
    """Drain the per-endpoint throttle counts and emit one observation each."""
    common = _get_common_attributes()

    observations: List[Observation] = []
    for key, value in drain(REQUEST_THROTTLE_NAME).items():
        attributes = dict(common)
        attributes["version"] = VERSION
        attributes["endpoint"] = key[0]
        attributes["host"] = key[1]
        attributes["statusCode"] = key[2]
        observations.append(Observation(value, attributes))
    return observations


def _observe_request_exception_count(options: CallbackOptions) -> Iterable[Observation]:
    """Drain the per-endpoint exception counts and emit one observation each."""
    common = _get_common_attributes()

    observations: List[Observation] = []
    for key, value in drain(REQUEST_EXCEPTION_NAME).items():
        attributes = dict(common)
        attributes["version"] = VERSION
        attributes["endpoint"] = key[0]
        attributes["host"] = key[1]
        attributes["exceptionType"] = key[2]
        observations.append(Observation(value, attributes))
    return observations


def register_network_gauges():
    try:
        from azure.monitor.opentelemetry.exporter.statsbeat._manager import StatsbeatManager  # type: ignore[import-not-found] # pylint: disable=line-too-long
    except ImportError:
        logger.debug("Upstream statsbeat unavailable; skipping network gauges.")
        return
    manager = StatsbeatManager()
    for metric, callback in (
        (_REQ_SUCCESS_NAME[0], _observe_request_success_count),
        (_REQ_DURATION_NAME[0], _observe_request_duration),
        (_REQ_FAILURE_NAME[0], _observe_request_failure_count),
        (_REQ_RETRY_NAME[0], _observe_request_retry_count),
        (_REQ_THROTTLE_NAME[0], _observe_request_throttle_count),
        (_REQ_EXCEPTION_NAME[0], _observe_request_exception_count),
    ):
        manager.add_additional_metric_callbacks(metric, callback)
