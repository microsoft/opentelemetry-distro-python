from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from microsoft.opentelemetry.a365.core import (
    AgentDetails,
    ApplyGuardrailScope,
    GuardrailDecisionType,
    GuardrailDetails,
    GuardrailFinding,
    GuardrailRiskSeverity,
    GuardrailTargetType,
    Request,
    UserDetails,
)

DENY_TRIGGER = "sample-blocked-content"
SAMPLE_INPUT_VALUE = "sample://guardrail/input"
SAMPLE_ALLOWED_OUTPUT = "sample://guardrail/allowed"
SAMPLE_BLOCKED_OUTPUT = "sample://guardrail/blocked"
BLOCKED_RESPONSE = "Your request was blocked by the sample input guardrail."


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    response_message: str | None = None


def evaluate_input_guardrail(
    user_message: str,
    agent_details: AgentDetails,
    request: Request,
) -> GuardrailResult:
    denied = DENY_TRIGGER in user_message.lower()
    decision_type = GuardrailDecisionType.DENY if denied else GuardrailDecisionType.ALLOW
    decision_reason = (
        "Deterministic sample trigger matched."
        if denied
        else "Deterministic sample policy allowed the request."
    )
    decision_code = "SAMPLE_BLOCKED_CONTENT" if denied else "SAMPLE_ALLOWED"
    output_value = SAMPLE_BLOCKED_OUTPUT if denied else SAMPLE_ALLOWED_OUTPUT
    risk_severity = GuardrailRiskSeverity.HIGH if denied else GuardrailRiskSeverity.NONE
    risk_score = 1.0 if denied else 0.0

    details = GuardrailDetails(
        target_type=GuardrailTargetType.LLM_INPUT,
        decision_type=decision_type,
        guardian_name="Sample Input Policy",
        guardian_id="sample-guardian-001",
        guardian_provider_name="microsoft.sample.local",
        guardian_version="1.0.0",
        target_id="sample-input-001",
        decision_reason=decision_reason,
        decision_code=decision_code,
        policy_id="sample-policy-001",
        policy_name="Sample Blocked Content Policy",
        policy_version="1.0.0",
        content_input_hash=f"sha256:{sha256(SAMPLE_INPUT_VALUE.encode('utf-8')).hexdigest()}",
        content_modified=False,
        external_event_id="sample-security-event-001",
    )
    user_details = UserDetails(
        user_id="sample-user-001",
        user_email="sample.user@example.invalid",
        user_name="Sample User",
        user_client_ip="192.0.2.1",
    )

    with ApplyGuardrailScope.start(
        details=details,
        agent_details=agent_details,
        request=request,
        user_details=user_details,
    ) as scope:
        scope.record_content_input(SAMPLE_INPUT_VALUE)
        scope.record_content_output(output_value)
        scope.record_finding(
            GuardrailFinding(
                risk_category="sample_blocked_content",
                risk_severity=risk_severity,
                policy_decision_type=decision_type,
                policy_id="sample-policy-001",
                policy_name="Sample Blocked Content Policy",
                policy_version="1.0.0",
                risk_score=risk_score,
                risk_metadata=["detector:deterministic", "content:fixed-non-sensitive"],
            )
        )

    return GuardrailResult(
        allowed=not denied,
        response_message=BLOCKED_RESPONSE if denied else None,
    )
