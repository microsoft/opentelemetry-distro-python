from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import re
import sys

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

SAMPLE_SRC = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SAMPLE_SRC))

from microsoft.opentelemetry.a365.core import AgentDetails, Request
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_CALLER_CLIENT_IP_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_GUARDIAN_ID_KEY,
    GEN_AI_GUARDIAN_NAME_KEY,
    GEN_AI_GUARDIAN_PROVIDER_NAME_KEY,
    GEN_AI_GUARDIAN_VERSION_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY,
    GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY,
    GEN_AI_SECURITY_CONTENT_MODIFIED_KEY,
    GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY,
    GEN_AI_SECURITY_DECISION_CODE_KEY,
    GEN_AI_SECURITY_DECISION_REASON_KEY,
    GEN_AI_SECURITY_DECISION_TYPE_KEY,
    GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY,
    GEN_AI_SECURITY_FINDING_EVENT_NAME,
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
    TELEMETRY_SDK_LANGUAGE_KEY,
    TELEMETRY_SDK_NAME_KEY,
    TELEMETRY_SDK_VERSION_KEY,
    TENANT_ID_KEY,
    USER_EMAIL_KEY,
    USER_ID_KEY,
    USER_NAME_KEY,
)
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from services.guardrail_service import evaluate_input_guardrail
from utils.payload_logging_exporter import (
    PAYLOAD_END_MARKER,
    PAYLOAD_START_MARKER,
    GuardrailPayloadLoggingExporter,
)


def test_guardrail_payload_uses_exact_exporter_contract(monkeypatch):
    provider = TracerProvider()
    exporter = GuardrailPayloadLoggingExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setattr(
        OpenTelemetryScope,
        "_tracer",
        provider.get_tracer("kairo-payload-test"),
    )
    output = StringIO()

    try:
        with redirect_stdout(output):
            evaluate_input_guardrail(
                "ordinary request",
                AgentDetails(
                    agent_id="agent-123",
                    agent_name="Kairo Guardrail Sample",
                    tenant_id="tenant-456",
                ),
                Request(conversation_id="conversation-789"),
            )
    finally:
        provider.shutdown()
        OpenTelemetryScope._tracer = None

    text = output.getvalue()
    body = text.split(PAYLOAD_START_MARKER, 1)[1].split(PAYLOAD_END_MARKER, 1)[0].strip()
    payload = json.loads(body)

    assert set(payload) == {"resourceSpans"}
    resource_span = payload["resourceSpans"][0]
    assert set(resource_span) == {"resource", "scopeSpans"}
    assert set(resource_span["resource"]) == {"attributes"}
    scope_span = resource_span["scopeSpans"][0]
    assert set(scope_span) == {"scope", "spans"}
    assert set(scope_span["scope"]) == {"name", "version"}

    span = scope_span["spans"][0]
    assert set(span) == {
        "traceId",
        "spanId",
        "parentSpanId",
        "name",
        "kind",
        "startTimeUnixNano",
        "endTimeUnixNano",
        "attributes",
        "events",
        "links",
        "status",
    }
    assert re.fullmatch(r"[0-9a-f]{32}", span["traceId"])
    assert re.fullmatch(r"[0-9a-f]{16}", span["spanId"])
    assert isinstance(span["startTimeUnixNano"], int)
    assert isinstance(span["endTimeUnixNano"], int)
    assert set(span["status"]) == {"code", "message"}

    attributes = span["attributes"]
    expected_attributes = {
        GEN_AI_OPERATION_NAME_KEY: "apply_guardrail",
        GEN_AI_SECURITY_TARGET_TYPE_KEY: "llm_input",
        GEN_AI_SECURITY_DECISION_TYPE_KEY: "allow",
        GEN_AI_GUARDIAN_ID_KEY: "sample-guardian-001",
        GEN_AI_GUARDIAN_NAME_KEY: "Sample Input Policy",
        GEN_AI_GUARDIAN_PROVIDER_NAME_KEY: "microsoft.sample.local",
        GEN_AI_GUARDIAN_VERSION_KEY: "1.0.0",
        GEN_AI_SECURITY_TARGET_ID_KEY: "sample-input-001",
        GEN_AI_SECURITY_DECISION_REASON_KEY: "Deterministic sample policy allowed the request.",
        GEN_AI_SECURITY_DECISION_CODE_KEY: "SAMPLE_ALLOWED",
        GEN_AI_SECURITY_POLICY_ID_KEY: "sample-policy-001",
        GEN_AI_SECURITY_POLICY_NAME_KEY: "Sample Blocked Content Policy",
        GEN_AI_SECURITY_POLICY_VERSION_KEY: "1.0.0",
        GEN_AI_SECURITY_CONTENT_MODIFIED_KEY: False,
        GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY: "sample-security-event-001",
        GEN_AI_CONVERSATION_ID_KEY: "conversation-789",
        USER_ID_KEY: "sample-user-001",
        USER_EMAIL_KEY: "sample.user@example.invalid",
        USER_NAME_KEY: "Sample User",
        GEN_AI_CALLER_CLIENT_IP_KEY: "192.0.2.1",
        GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY: "sample://guardrail/input",
        GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY: "sample://guardrail/allowed",
        GEN_AI_AGENT_ID_KEY: "agent-123",
        GEN_AI_AGENT_NAME_KEY: "Kairo Guardrail Sample",
        TENANT_ID_KEY: "tenant-456",
        TELEMETRY_SDK_NAME_KEY: "microsoft-opentelemetry",
        TELEMETRY_SDK_LANGUAGE_KEY: "python",
    }
    for key, value in expected_attributes.items():
        assert attributes[key] == value
    assert isinstance(attributes[TELEMETRY_SDK_VERSION_KEY], str)
    assert attributes[TELEMETRY_SDK_VERSION_KEY]
    assert re.fullmatch(
        r"sha256:[0-9a-f]{64}",
        attributes[GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY],
    )

    event = span["events"][0]
    assert set(event) == {"timeUnixNano", "name", "attributes"}
    assert event["name"] == GEN_AI_SECURITY_FINDING_EVENT_NAME
    assert event["attributes"] == {
        GEN_AI_SECURITY_RISK_CATEGORY_KEY: "sample_blocked_content",
        GEN_AI_SECURITY_RISK_SEVERITY_KEY: "none",
        GEN_AI_SECURITY_RISK_SCORE_KEY: 0.0,
        GEN_AI_SECURITY_RISK_METADATA_KEY: [
            "detector:deterministic",
            "content:fixed-non-sensitive",
        ],
        GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY: "allow",
        GEN_AI_SECURITY_POLICY_ID_KEY: "sample-policy-001",
        GEN_AI_SECURITY_POLICY_NAME_KEY: "Sample Blocked Content Policy",
        GEN_AI_SECURITY_POLICY_VERSION_KEY: "1.0.0",
    }
