# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Network statsbeat wrappers for OTLP exporters.

The upstream OTLP exporters do not expose HTTP status codes — only the
``ExportResult`` enum.  These wrappers capture the SUCCESS signal so the
network statsbeat pipeline can record success/failures/retries per
endpoint.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult, MetricsData
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from microsoft.opentelemetry._sdkstats._utils import record_success


def _endpoint_host(exporter: Any) -> str:
    raw = getattr(exporter, "_endpoint", None)
    if not isinstance(raw, str) or not raw:
        return "unknown"
    try:
        return urlparse(raw).hostname or raw
    except (TypeError, ValueError):
        return raw


class _NetworkStatsSpanExporter(SpanExporter):
    """Span exporter decorator that records ``request_success_count``."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner
        self._endpoint = _endpoint_host(inner)

    def export(self, spans: Any) -> SpanExportResult:  # type: ignore[override]
        result = self._inner.export(spans)
        if result == SpanExportResult.SUCCESS:
            record_success(self._endpoint)
        return result

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)


class _NetworkStatsMetricExporter(MetricExporter):
    """Metric exporter decorator that records ``request_success_count``."""

    def __init__(self, inner: MetricExporter) -> None:
        # Don't call super().__init__() — preserve inner's preferences.
        # pylint: disable=super-init-not-called
        self._inner = inner
        self._endpoint = _endpoint_host(inner)

    @property
    def _preferred_temporality(self):  # type: ignore[no-untyped-def]
        return getattr(self._inner, "_preferred_temporality", None)

    @property
    def _preferred_aggregation(self):  # type: ignore[no-untyped-def]
        return getattr(self._inner, "_preferred_aggregation", None)

    def export(  # type: ignore[override]
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        result = self._inner.export(metrics_data, timeout_millis, **kwargs)
        if result == MetricExportResult.SUCCESS:
            record_success(self._endpoint)
        return result

    def force_flush(self, timeout_millis: float = 10_000) -> bool:  # type: ignore[override]
        return self._inner.force_flush(timeout_millis)

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:  # type: ignore[override]
        self._inner.shutdown(timeout_millis, **kwargs)


class _NetworkStatsLogExporter(LogRecordExporter):
    """Log exporter decorator that records ``request_success_count``."""

    def __init__(self, inner: LogRecordExporter) -> None:
        self._inner = inner
        self._endpoint = _endpoint_host(inner)

    def export(self, batch: Any) -> LogRecordExportResult:  # type: ignore[override]
        result = self._inner.export(batch)
        if result == LogRecordExportResult.SUCCESS:
            record_success(self._endpoint)
        return result

    def shutdown(self) -> None:
        self._inner.shutdown()


__all__ = [
    "_NetworkStatsSpanExporter",
    "_NetworkStatsMetricExporter",
    "_NetworkStatsLogExporter",
]
