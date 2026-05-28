# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""OpenTelemetry tracing scope for guardrail (security guardian) evaluations."""

from __future__ import annotations

from opentelemetry.trace import SpanKind

from microsoft.opentelemetry.a365.core.agent_details import AgentDetails
from microsoft.opentelemetry.a365.core.constants import (
    APPLY_GUARDRAIL_OPERATION_NAME,
    CHANNEL_LINK_KEY,
    CHANNEL_NAME_KEY,
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
    USER_EMAIL_KEY,
    USER_ID_KEY,
    USER_NAME_KEY,
)
from microsoft.opentelemetry.a365.core.guardrail_details import GuardrailDetails
from microsoft.opentelemetry.a365.core.guardrail_finding import GuardrailFinding
from microsoft.opentelemetry.a365.core.message_utils import normalize_input_messages, serialize_messages
from microsoft.opentelemetry.a365.core.models.messages import InputMessagesParam
from microsoft.opentelemetry.a365.core.models.user_details import UserDetails
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from microsoft.opentelemetry.a365.core.request import Request
from microsoft.opentelemetry.a365.core.span_details import SpanDetails
from microsoft.opentelemetry.a365.core.utils import validate_and_normalize_ip


class ApplyGuardrailScope(OpenTelemetryScope):
    """Provides OpenTelemetry tracing scope for security guardrail evaluations.

    Guardian spans SHOULD be children of the operation span they are protecting
    (e.g., inference or execute_tool spans). Multiple guardian spans MAY exist
    under a single operation span if multiple guardians are chained.

    Example usage::

        from microsoft.opentelemetry.a365.core import (
            ApplyGuardrailScope, GuardrailDetails, AgentDetails,
            GuardrailDecisionType, GuardrailTargetType, GuardrailRiskSeverity,
            GuardrailFinding,
        )

        details = GuardrailDetails(
            target_type=GuardrailTargetType.LLM_INPUT,
            decision_type=GuardrailDecisionType.ALLOW,
            guardian_name="Azure Content Safety",
        )

        with ApplyGuardrailScope.start(details, agent_details) as scope:
            # ... run guardrail evaluation ...
            scope.record_finding(GuardrailFinding(
                risk_category="hate_speech",
                risk_severity=GuardrailRiskSeverity.HIGH,
                risk_score=0.95,
            ))
            scope.record_decision(GuardrailDecisionType.DENY, "Blocked by policy")
    """

    @staticmethod
    def start(
        details: GuardrailDetails,
        agent_details: AgentDetails,
        request: Request | None = None,
        user_details: UserDetails | None = None,
        span_details: SpanDetails | None = None,
    ) -> "ApplyGuardrailScope":
        """Create and start a new scope for guardrail evaluation tracing.

        Args:
            details: Guardrail evaluation details (required).
            agent_details: Agent identity details (required).
            request: Optional request context (conversation ID, channel, content).
            user_details: Optional human user details.
            span_details: Optional span configuration (parent context, timing, kind).

        Returns:
            A new ApplyGuardrailScope instance.
        """
        return ApplyGuardrailScope(details, agent_details, request, user_details, span_details)

    def __init__(
        self,
        details: GuardrailDetails,
        agent_details: AgentDetails,
        request: Request | None = None,
        user_details: UserDetails | None = None,
        span_details: SpanDetails | None = None,
    ):
        """Initialize the guardrail scope.

        Args:
            details: Guardrail evaluation details.
            agent_details: Agent identity details.
            request: Optional request context.
            user_details: Optional human user details.
            span_details: Optional span configuration.
        """
        # Default span kind to INTERNAL for guardrail evaluations
        resolved_span_details = (
            SpanDetails(
                span_kind=span_details.span_kind if span_details and span_details.span_kind else SpanKind.INTERNAL,
                parent_context=span_details.parent_context if span_details else None,
                start_time=span_details.start_time if span_details else None,
                end_time=span_details.end_time if span_details else None,
                span_links=span_details.span_links if span_details else None,
            )
            if span_details
            else SpanDetails(span_kind=SpanKind.INTERNAL)
        )

        super().__init__(
            operation_name=APPLY_GUARDRAIL_OPERATION_NAME,
            activity_name=self._build_activity_name(details),
            agent_details=agent_details,
            span_details=resolved_span_details,
        )

        # Set guardrail-specific attributes
        self.set_tag_maybe(GEN_AI_SECURITY_TARGET_TYPE_KEY, details.target_type)
        self.set_tag_maybe(GEN_AI_SECURITY_DECISION_TYPE_KEY, details.decision_type)
        self.set_tag_maybe(GEN_AI_GUARDIAN_ID_KEY, details.guardian_id)
        self.set_tag_maybe(GEN_AI_GUARDIAN_NAME_KEY, details.guardian_name)
        self.set_tag_maybe(GEN_AI_GUARDIAN_PROVIDER_NAME_KEY, details.guardian_provider_name)
        self.set_tag_maybe(GEN_AI_GUARDIAN_VERSION_KEY, details.guardian_version)
        self.set_tag_maybe(GEN_AI_SECURITY_TARGET_ID_KEY, details.target_id)
        self.set_tag_maybe(GEN_AI_SECURITY_DECISION_REASON_KEY, details.decision_reason)
        self.set_tag_maybe(GEN_AI_SECURITY_DECISION_CODE_KEY, details.decision_code)
        self.set_tag_maybe(GEN_AI_SECURITY_POLICY_ID_KEY, details.policy_id)
        self.set_tag_maybe(GEN_AI_SECURITY_POLICY_NAME_KEY, details.policy_name)
        self.set_tag_maybe(GEN_AI_SECURITY_POLICY_VERSION_KEY, details.policy_version)
        self.set_tag_maybe(GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY, details.content_input_hash)
        self.set_tag_maybe(GEN_AI_SECURITY_CONTENT_MODIFIED_KEY, details.content_modified)
        self.set_tag_maybe(GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY, details.external_event_id)

        # Set request context if provided
        if request:
            self.set_tag_maybe(GEN_AI_CONVERSATION_ID_KEY, request.conversation_id)
            if request.channel:
                self.set_tag_maybe(CHANNEL_NAME_KEY, request.channel.name)
                self.set_tag_maybe(CHANNEL_LINK_KEY, request.channel.link)

        # Set user details if provided
        if user_details:
            self.set_tag_maybe(USER_ID_KEY, user_details.user_id)
            self.set_tag_maybe(USER_EMAIL_KEY, user_details.user_email)
            self.set_tag_maybe(USER_NAME_KEY, user_details.user_name)
            self.set_tag_maybe(
                GEN_AI_CALLER_CLIENT_IP_KEY,
                validate_and_normalize_ip(user_details.user_client_ip),
            )

    @staticmethod
    def _build_activity_name(details: GuardrailDetails) -> str:
        """Build the span display name from guardrail details."""
        if details.guardian_name:
            return f"{APPLY_GUARDRAIL_OPERATION_NAME} {details.guardian_name} {details.target_type}"
        return f"{APPLY_GUARDRAIL_OPERATION_NAME} {details.target_type}"

    def record_decision(self, decision_type: str, reason: str | None = None) -> None:
        """Update the guardrail decision on the span.

        Use this to update the decision mid-flight if the initial decision
        changes after evaluation completes.

        Args:
            decision_type: The decision type (use GuardrailDecisionType constants).
            reason: Optional human-readable reason for the decision.
        """
        self.set_tag_maybe(GEN_AI_SECURITY_DECISION_TYPE_KEY, decision_type)
        if reason is not None:
            self.set_tag_maybe(GEN_AI_SECURITY_DECISION_REASON_KEY, reason)

    def record_content_output(self, output_value: str) -> None:
        """Record the sanitized/modified output content (opt-in).

        This is an opt-in field for recording output content after guardrail
        processing. Only set this when content capture is explicitly enabled.

        Args:
            output_value: The output content string.
        """
        self.set_tag_maybe(GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY, output_value)

    def record_content_input(self, input_value: InputMessagesParam | str) -> None:
        """Record the input content being evaluated (opt-in).

        This is an opt-in field for recording input content sent to the
        guardrail. Only set this when content capture is explicitly enabled.

        Accepts plain strings or structured ``InputMessages`` containers.
        Structured messages are normalized and serialized to a JSON string
        before being set as an attribute.

        Args:
            input_value: The input content as a string or InputMessagesParam.
        """
        if isinstance(input_value, str):
            self.set_tag_maybe(GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY, input_value)
        else:
            wrapper = normalize_input_messages(input_value)
            self.set_tag_maybe(GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY, serialize_messages(wrapper))

    def record_finding(self, finding: GuardrailFinding) -> None:
        """Record a security finding as a span event.

        Each call adds a separate ``microsoft.security.finding`` event to the
        span. Multiple findings can be recorded for a single guardrail evaluation.

        Args:
            finding: The security finding to record.
        """
        if not self._span or not self._is_telemetry_enabled():
            return

        attributes: dict[str, str | float | list[str]] = {
            GEN_AI_SECURITY_RISK_CATEGORY_KEY: finding.risk_category,
            GEN_AI_SECURITY_RISK_SEVERITY_KEY: finding.risk_severity,
        }

        if finding.risk_score is not None:
            attributes[GEN_AI_SECURITY_RISK_SCORE_KEY] = finding.risk_score
        if finding.risk_metadata is not None:
            attributes[GEN_AI_SECURITY_RISK_METADATA_KEY] = finding.risk_metadata
        if finding.policy_decision_type is not None:
            attributes[GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY] = finding.policy_decision_type
        if finding.policy_id is not None:
            attributes[GEN_AI_SECURITY_POLICY_ID_KEY] = finding.policy_id
        if finding.policy_name is not None:
            attributes[GEN_AI_SECURITY_POLICY_NAME_KEY] = finding.policy_name
        if finding.policy_version is not None:
            attributes[GEN_AI_SECURITY_POLICY_VERSION_KEY] = finding.policy_version

        self._span.add_event(GEN_AI_SECURITY_FINDING_EVENT_NAME, attributes=attributes)
