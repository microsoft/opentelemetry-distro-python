# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# -------------------------------------------------------------------------

import os
from dataclasses import dataclass, field
from logging import getLogger
from typing import Optional

from opentelemetry.sdk.trace.export import SpanProcessor
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk._logs import LogRecordProcessor

from microsoft.opentelemetry._constants import (
    _OTEL_EXPORTER_OTLP_ENDPOINT,
    _OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    _OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
    _OTEL_EXPORTER_OTLP_LOGS_ENDPOINT,
)

_logger = getLogger(__name__)


@dataclass
class OtlpHandlers:
    span_processor: Optional[SpanProcessor] = field(default=None)
    metric_reader: Optional[MetricReader] = field(default=None)
    log_record_processor: Optional[LogRecordProcessor] = field(default=None)


def is_otlp_enabled() -> bool:
    """Determines whether OTLP export should be enabled.

    OTLP is enabled when any supported OTLP endpoint environment variable is set:
    ``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``,
    ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``, or ``OTEL_EXPORTER_OTLP_LOGS_ENDPOINT``.
    """
    return any(
        os.environ.get(env_var)
        for env_var in (
            _OTEL_EXPORTER_OTLP_ENDPOINT,
            _OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
            _OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
            _OTEL_EXPORTER_OTLP_LOGS_ENDPOINT,
        )
    )


def create_otlp_components(
    enable_traces: bool = True,
    enable_metrics: bool = True,
    enable_logs: bool = True,
) -> OtlpHandlers:
    """Creates OTLP HTTP exporters for the requested signals.

    Only the signals that are enabled will have exporters created.
    All configuration is driven by the standard OpenTelemetry OTLP environment
    variables.  The underlying ``opentelemetry-exporter-otlp-proto-http``
    packages read these variables automatically -- no programmatic config is
    required.

    Supported environment variables
    ===============================

    General (apply to all signals)
    ------------------------------
    - ``OTEL_EXPORTER_OTLP_ENDPOINT`` -- Base endpoint URL for all signals.
    - ``OTEL_EXPORTER_OTLP_HEADERS`` -- Comma-separated key=value pairs.
    - ``OTEL_EXPORTER_OTLP_TIMEOUT`` -- Max time in milliseconds per export.
    - ``OTEL_EXPORTER_OTLP_COMPRESSION`` -- ``gzip`` or ``none``.

    Per-signal overrides follow the pattern
    ``OTEL_EXPORTER_OTLP_{TRACES,METRICS,LOGS}_{ENDPOINT,HEADERS,TIMEOUT,COMPRESSION}``.
    """
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor


    # from opentelemetry.sdk.trace.export import SpanExporter
    # from opentelemetry.sdk.metrics.export import MetricExporter
    # from opentelemetry.sdk._logs.export import LogRecordExporter
    # from microsoft.opentelemetry._sdkstats import is_sdkstats_enabled
    # from microsoft.opentelemetry._sdkstats._otlp_wrapper import (
    #     _NetworkStatsLogExporter,
    #     _NetworkStatsMetricExporter,
    #     _NetworkStatsSpanExporter,
    # )
    # record_network_sdkstats = is_sdkstats_enabled()

    components = OtlpHandlers()

    if enable_traces:
        components.span_processor = BatchSpanProcessor(OTLPSpanExporter())
        # span_exporter: SpanExporter = OTLPSpanExporter()
        # if record_network_sdkstats:
        #     span_exporter = _NetworkStatsSpanExporter(span_exporter)
        # components.span_processor = BatchSpanProcessor(span_exporter)

    if enable_metrics:
        components.metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        # metric_exporter: MetricExporter = OTLPMetricExporter()
        # if record_network_sdkstats:
        #     metric_exporter = _NetworkStatsMetricExporter(metric_exporter)
        # components.metric_reader = PeriodicExportingMetricReader(metric_exporter)

    if enable_logs:
        components.log_record_processor = BatchLogRecordProcessor(OTLPLogExporter())
        # log_exporter: LogRecordExporter = OTLPLogExporter()
        # if record_network_sdkstats:
        #     log_exporter = _NetworkStatsLogExporter(log_exporter)
        # components.log_record_processor = BatchLogRecordProcessor(log_exporter)

    return components
