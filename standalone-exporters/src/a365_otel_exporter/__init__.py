"""A365 OpenTelemetry SpanExporter - export spans to Agent 365 Observability."""

from a365_otel_exporter.exporter import A365SpanExporter, A365ExporterOptions
from a365_otel_exporter.baggage import BaggageBuilder, set_a365_span_attributes
from a365_otel_exporter.auth import TokenResolver

__all__ = [
    "A365SpanExporter",
    "A365ExporterOptions",
    "BaggageBuilder",
    "set_a365_span_attributes",
    "TokenResolver",
]

__version__ = "0.1.0"
