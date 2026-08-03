from hashlib import sha256
from pathlib import Path
import sys

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

SAMPLE_SRC = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SAMPLE_SRC))

from microsoft.opentelemetry.a365.core import AgentDetails, Request
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_CALLER_CLIENT_IP_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_GUARDIAN_ID_KEY,
    GEN_AI_GUARDIAN_NAME_KEY,
    GEN_AI_GUARDIAN_PROVIDER_NAME_KEY,
    GEN_AI_GUARDIAN_VERSION_KEY,
    GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY,
    GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY,
    GEN_AI_SECURITY_CONTENT_MODIFIED_KEY,
    GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY,
    GEN_AI_SECURITY_DECISION_CODE_KEY,
    GEN_AI_SECURITY_DECISION_REASON_KEY,
    GEN_AI_SECURITY_DECISION_TYPE_KEY,
    GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY,
    GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY,
    GEN_AI_SECURITY_POLICY_ID_KEY,
    GEN_AI_SECURITY_POLICY_NAME_KEY,
    GEN_AI_SECURITY_POLICY_VERSION_KEY,
    GEN_AI_SECURITY_RISK_CATEGORY_KEY,
    GEN_AI_SECURITY_RISK_METADATA_KEY,
    GEN_AI_SECURITY_RISK_SCORE_KEY,
    GEN_AI_SECURITY_RISK_SEVERITY_KEY,
    GEN_AI_SECURITY_TARGET_ID_KEY,
    GEN_AI_SECURITY_TARGET_TYPE_KEY,
    GEN_AI_SECURITY_FINDING_EVENT_NAME,
    GEN_AI_OPERATION_NAME_KEY,
    USER_EMAIL_KEY,
    USER_ID_KEY,
    USER_NAME_KEY,
)
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from services.guardrail_service import (
    BLOCKED_RESPONSE,
    DENY_TRIGGER,
    SAMPLE_ALLOWED_OUTPUT,
    SAMPLE_BLOCKED_OUTPUT,
    SAMPLE_INPUT_VALUE,
    GuardrailResult,
    evaluate_input_guardrail,
)


def _agent_details() -> AgentDetails:
    return AgentDetails(
        agent_id="agent-123",
        agent_name="Kairo Guardrail Sample",
        tenant_id="tenant-456",
    )


def _request() -> Request:
    return Request(conversation_id="conversation-789")


def _run_guardrail(message: str, monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setattr(
        OpenTelemetryScope,
        "_tracer",
        provider.get_tracer("kairo-guardrail-test"),
    )
    try:
        result = evaluate_input_guardrail(message, _agent_details(), _request())
        spans = exporter.get_finished_spans()
        return result, spans
    finally:
        provider.shutdown()
        OpenTelemetryScope._tracer = None


def test_allow_result_and_complete_span(monkeypatch):
    result, spans = _run_guardrail("What is the weather?", monkeypatch)

    assert result == GuardrailResult(allowed=True, response_message=None)
    assert len(spans) == 1

    span = spans[0]
    assert span.name == "apply_guardrail Sample Input Policy llm_input"
    assert span.attributes[GEN_AI_OPERATION_NAME_KEY] == "apply_guardrail"
    assert span.attributes[GEN_AI_SECURITY_TARGET_TYPE_KEY] == "llm_input"
    assert span.attributes[GEN_AI_SECURITY_DECISION_TYPE_KEY] == "allow"
    assert span.attributes[GEN_AI_GUARDIAN_NAME_KEY] == "Sample Input Policy"
    assert span.attributes[GEN_AI_GUARDIAN_ID_KEY] == "sample-guardian-001"
    assert span.attributes[GEN_AI_GUARDIAN_PROVIDER_NAME_KEY] == "microsoft.sample.local"
    assert span.attributes[GEN_AI_GUARDIAN_VERSION_KEY] == "1.0.0"
    assert span.attributes[GEN_AI_SECURITY_TARGET_ID_KEY] == "sample-input-001"
    assert span.attributes[GEN_AI_SECURITY_DECISION_REASON_KEY] == "Deterministic sample policy allowed the request."
    assert span.attributes[GEN_AI_SECURITY_DECISION_CODE_KEY] == "SAMPLE_ALLOWED"
    assert span.attributes[GEN_AI_SECURITY_POLICY_ID_KEY] == "sample-policy-001"
    assert span.attributes[GEN_AI_SECURITY_POLICY_NAME_KEY] == "Sample Blocked Content Policy"
    assert span.attributes[GEN_AI_SECURITY_POLICY_VERSION_KEY] == "1.0.0"
    assert span.attributes[GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY] == f"sha256:{sha256(SAMPLE_INPUT_VALUE.encode('utf-8')).hexdigest()}"
    assert span.attributes[GEN_AI_SECURITY_CONTENT_MODIFIED_KEY] is False
    assert span.attributes[GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY] == "sample-security-event-001"
    assert span.attributes[GEN_AI_CONVERSATION_ID_KEY] == "conversation-789"
    assert span.attributes[USER_ID_KEY] == "sample-user-001"
    assert span.attributes[USER_EMAIL_KEY] == "sample.user@example.invalid"
    assert span.attributes[USER_NAME_KEY] == "Sample User"
    assert span.attributes[GEN_AI_CALLER_CLIENT_IP_KEY] == "192.0.2.1"
    assert span.attributes[GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY] == SAMPLE_INPUT_VALUE
    assert span.attributes[GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY] == SAMPLE_ALLOWED_OUTPUT
    assert len(span.events) == 1

    finding = span.events[0]
    assert finding.name == GEN_AI_SECURITY_FINDING_EVENT_NAME
    assert finding.attributes[GEN_AI_SECURITY_RISK_CATEGORY_KEY] == "sample_blocked_content"
    assert finding.attributes[GEN_AI_SECURITY_RISK_SEVERITY_KEY] == "none"
    assert finding.attributes[GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY] == "allow"
    assert finding.attributes[GEN_AI_SECURITY_POLICY_ID_KEY] == "sample-policy-001"
    assert finding.attributes[GEN_AI_SECURITY_POLICY_NAME_KEY] == "Sample Blocked Content Policy"
    assert finding.attributes[GEN_AI_SECURITY_POLICY_VERSION_KEY] == "1.0.0"
    assert finding.attributes[GEN_AI_SECURITY_RISK_SCORE_KEY] == 0.0
    assert list(finding.attributes[GEN_AI_SECURITY_RISK_METADATA_KEY]) == [
        "detector:deterministic",
        "content:fixed-non-sensitive",
    ]


def test_deny_result_and_complete_span(monkeypatch):
    result, spans = _run_guardrail(f"Please process {DENY_TRIGGER}", monkeypatch)

    assert result.allowed is False
    assert result.response_message == BLOCKED_RESPONSE
    assert len(spans) == 1

    span = spans[0]
    assert span.attributes[GEN_AI_SECURITY_DECISION_TYPE_KEY] == "deny"
    assert span.attributes[GEN_AI_SECURITY_DECISION_CODE_KEY] == "SAMPLE_BLOCKED_CONTENT"
    assert span.attributes[GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY] == SAMPLE_BLOCKED_OUTPUT
    assert span.events[0].attributes[GEN_AI_SECURITY_RISK_SEVERITY_KEY] == "high"
