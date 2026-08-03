from __future__ import annotations

from collections.abc import Sequence

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult

from microsoft.opentelemetry.a365.constants import GEN_AI_OPERATION_NAME_KEY
from microsoft.opentelemetry.a365.core.exporters.agent365_exporter import _Agent365Exporter

PAYLOAD_START_MARKER = "=== BEGIN KAIRO GUARDRAIL EXPORT JSON ==="
PAYLOAD_END_MARKER = "=== END KAIRO GUARDRAIL EXPORT JSON ==="


class GuardrailPayloadLoggingExporter(_Agent365Exporter):
    def __init__(self) -> None:
        super().__init__(token_resolver=lambda _agent_id, _tenant_id: "sample-console-token")

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        guardrail_spans = [
            span
            for span in spans
            if (span.attributes or {}).get(GEN_AI_OPERATION_NAME_KEY) == "apply_guardrail"
        ]
        if not guardrail_spans:
            return SpanExportResult.SUCCESS
        return super().export(guardrail_spans)

    def _post_with_retries(
        self,
        _url: str,
        body: str,
        _headers: dict[str, str | bytes],
    ) -> bool:
        print(PAYLOAD_START_MARKER)
        print(body)
        print(PAYLOAD_END_MARKER)
        return True


def register_guardrail_payload_logging() -> None:
    provider = trace.get_tracer_provider()
    add_span_processor = getattr(provider, "add_span_processor", None)
    if add_span_processor is None:
        raise RuntimeError("The configured tracer provider cannot register span processors.")
    add_span_processor(SimpleSpanProcessor(GuardrailPayloadLoggingExporter()))
