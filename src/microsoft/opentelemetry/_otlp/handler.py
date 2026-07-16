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
    _OTEL_EXPORTER_OTLP_PROTOCOL,
    _OTEL_EXPORTER_OTLP_TRACES_PROTOCOL,
    _OTEL_EXPORTER_OTLP_METRICS_PROTOCOL,
    _OTEL_EXPORTER_OTLP_LOGS_PROTOCOL,
)

_logger = getLogger(__name__)

_HTTP_PROTOBUF = "http/protobuf"
_GRPC = "grpc"

_SIGNAL_PROTOCOL_ENV_VARS = {
    "traces": _OTEL_EXPORTER_OTLP_TRACES_PROTOCOL,
    "metrics": _OTEL_EXPORTER_OTLP_METRICS_PROTOCOL,
    "logs": _OTEL_EXPORTER_OTLP_LOGS_PROTOCOL,
}


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


def _resolve_protocol(signal: str) -> str:
    signal_env_var = _SIGNAL_PROTOCOL_ENV_VARS[signal]
    protocol = os.environ.get(signal_env_var) or os.environ.get(_OTEL_EXPORTER_OTLP_PROTOCOL) or _HTTP_PROTOBUF
    protocol = protocol.strip().lower()
    if protocol not in (_HTTP_PROTOBUF, _GRPC):
        raise ValueError(
            f"Unsupported OTLP protocol {protocol!r} for {signal}. "
            f"Set {signal_env_var} or {_OTEL_EXPORTER_OTLP_PROTOCOL} to {_HTTP_PROTOBUF!r} or {_GRPC!r}."
        )
    return protocol


def create_otlp_components(
    enable_traces: bool = True,
    enable_metrics: bool = True,
    enable_logs: bool = True,
) -> OtlpHandlers:
    """Creates OTLP exporters for the requested signals.

    Only the signals that are enabled will have exporters created.
    Protocol selection and exporter configuration are driven by the standard
    OpenTelemetry OTLP environment variables. Per-signal protocol settings
    override the general protocol setting. HTTP/protobuf remains the default
    for backward compatibility.

    Supported environment variables
    ===============================

    General (apply to all signals)
    ------------------------------
    - ``OTEL_EXPORTER_OTLP_ENDPOINT`` -- Base endpoint URL for all signals.
    - ``OTEL_EXPORTER_OTLP_HEADERS`` -- Comma-separated key=value pairs.
    - ``OTEL_EXPORTER_OTLP_TIMEOUT`` -- Max time in milliseconds per export.
    - ``OTEL_EXPORTER_OTLP_COMPRESSION`` -- ``gzip`` or ``none``.
    - ``OTEL_EXPORTER_OTLP_PROTOCOL`` -- ``http/protobuf`` or ``grpc``.

    Per-signal overrides follow the pattern
    ``OTEL_EXPORTER_OTLP_{TRACES,METRICS,LOGS}_{ENDPOINT,HEADERS,TIMEOUT,COMPRESSION,PROTOCOL}``.
    """
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
    from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter

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
        if _resolve_protocol("traces") == _GRPC:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcSpanExporter,
            )

            span_exporter: SpanExporter = GrpcSpanExporter()
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as HttpSpanExporter,
            )

            span_exporter = HttpSpanExporter()

        components.span_processor = BatchSpanProcessor(span_exporter)
        # span_exporter: SpanExporter = OTLPSpanExporter()
        # if record_network_sdkstats:
        #     span_exporter = _NetworkStatsSpanExporter(span_exporter)
        # components.span_processor = BatchSpanProcessor(span_exporter)

    if enable_metrics:
        if _resolve_protocol("metrics") == _GRPC:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter as GrpcMetricExporter,
            )

            metric_exporter: MetricExporter = GrpcMetricExporter()
        else:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter as HttpMetricExporter,
            )

            metric_exporter = HttpMetricExporter()

        components.metric_reader = PeriodicExportingMetricReader(metric_exporter)
        # metric_exporter: MetricExporter = OTLPMetricExporter()
        # if record_network_sdkstats:
        #     metric_exporter = _NetworkStatsMetricExporter(metric_exporter)
        # components.metric_reader = PeriodicExportingMetricReader(metric_exporter)

    if enable_logs:
        if _resolve_protocol("logs") == _GRPC:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                OTLPLogExporter as GrpcLogExporter,
            )

            log_exporter: LogRecordExporter = GrpcLogExporter()
        else:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                OTLPLogExporter as HttpLogExporter,
            )

            log_exporter = HttpLogExporter()

        components.log_record_processor = BatchLogRecordProcessor(log_exporter)
        # log_exporter: LogRecordExporter = OTLPLogExporter()
        # if record_network_sdkstats:
        #     log_exporter = _NetworkStatsLogExporter(log_exporter)
        # components.log_record_processor = BatchLogRecordProcessor(log_exporter)

    return components
