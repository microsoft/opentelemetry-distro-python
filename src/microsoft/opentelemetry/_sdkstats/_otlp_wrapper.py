# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Network statsbeat wrappers for OTLP HTTP exporters.

These classes subclass the upstream ``opentelemetry-exporter-otlp-proto-http``
exporters and override ``_export()`` -- the per-HTTP-attempt seam that
returns a ``requests.Response`` -- so we can classify each attempt by its
actual HTTP status code:

* 2xx                                 -> ``request_success_count``
* 402, 439 (throttle)                 -> ``request_throttle_count``
* 408, 429, 500, 502, 503, 504 (retry) -> ``request_retry_count``
* other 4xx / 5xx                     -> ``request_failure_count``
* network/SSL/serialization exception -> ``request_exception_count``

"""

from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from microsoft.opentelemetry._sdkstats._constants import (
    ENDPOINT_OTLP, 
    THROTTLE_STATUS_CODES, 
    RETRYABLE_STATUS_CODES,
)

from microsoft.opentelemetry._sdkstats._utils import (
    record_duration,
    record_exception,
    record_failure,
    record_retry,
    record_success,
    record_throttle,
)


def _endpoint_host(exporter: Any) -> str:
    raw = getattr(exporter, "_endpoint", None)
    if not isinstance(raw, str) or not raw:
        return "unknown"
    try:
        return urlparse(raw).hostname or raw
    except (TypeError, ValueError):
        return raw


def _classify(host: str, response: requests.Response) -> None:
    """Record one success/throttle/retry/failure based on HTTP status."""
    code = response.status_code
    if 200 <= code < 300:
        record_success(ENDPOINT_OTLP, host)
    elif code in THROTTLE_STATUS_CODES:
        record_throttle(ENDPOINT_OTLP, host, code)
    elif code in RETRYABLE_STATUS_CODES:
        record_retry(ENDPOINT_OTLP, host, code)
    else:
        record_failure(ENDPOINT_OTLP, host, code)


def _record_attempt(
    host: str,
    start: float,
    super_export,
    serialized_data: bytes,
    timeout_sec: Optional[float],
) -> requests.Response:
    """Shared per-attempt body: classify outcome, record duration in finally.

    ``super_export`` is the bound ``super()._export`` of the calling
    subclass, so all three signal exporters can share this body.
    """
    try:
        try:
            response = super_export(serialized_data, timeout_sec)
        except Exception as exc:  # noqa: BLE001
            record_exception(ENDPOINT_OTLP, host, type(exc).__name__)
            raise
        _classify(host, response)
        return response
    finally:
        record_duration(ENDPOINT_OTLP, host, time.time() - start)


class _NetworkStatsSpanExporter(OTLPSpanExporter):
    """OTLP span exporter that records per-attempt network statsbeat."""

    def _export(  # type: ignore[override]
        self,
        serialized_data: bytes,
        timeout_sec: Optional[float] = None,
    ) -> requests.Response:
        return _record_attempt(
            _endpoint_host(self),
            time.time(),
            super()._export,
            serialized_data,
            timeout_sec,
        )


class _NetworkStatsMetricExporter(OTLPMetricExporter):
    """OTLP metric exporter that records per-attempt network statsbeat."""

    def _export(  # type: ignore[override]
        self,
        serialized_data: bytes,
        timeout_sec: Optional[float] = None,
    ) -> requests.Response:
        return _record_attempt(
            _endpoint_host(self),
            time.time(),
            super()._export,
            serialized_data,
            timeout_sec,
        )


class _NetworkStatsLogExporter(OTLPLogExporter):
    """OTLP log exporter that records per-attempt network statsbeat."""

    def _export(  # type: ignore[override]
        self,
        serialized_data: bytes,
        timeout_sec: Optional[float] = None,
    ) -> requests.Response:
        return _record_attempt(
            _endpoint_host(self),
            time.time(),
            super()._export,
            serialized_data,
            timeout_sec,
        )


__all__ = [
    "_NetworkStatsSpanExporter",
    "_NetworkStatsMetricExporter",
    "_NetworkStatsLogExporter",
]
