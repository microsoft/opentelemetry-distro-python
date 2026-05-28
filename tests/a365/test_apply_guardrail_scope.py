# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind

from microsoft.opentelemetry.a365.core.agent_details import AgentDetails
from microsoft.opentelemetry.a365.core.apply_guardrail_scope import ApplyGuardrailScope
from microsoft.opentelemetry.a365.core.channel import Channel
from microsoft.opentelemetry.a365.core.constants import (
    APPLY_GUARDRAIL_OPERATION_NAME,
    CHANNEL_LINK_KEY,
    CHANNEL_NAME_KEY,
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
    USER_EMAIL_KEY,
    USER_ID_KEY,
    USER_NAME_KEY,
)
from microsoft.opentelemetry.a365.core.exporters.utils import (
    GEN_AI_OPERATION_NAMES,
    filter_and_partition_by_identity,
)
from microsoft.opentelemetry.a365.core.guardrail_decision_type import GuardrailDecisionType
from microsoft.opentelemetry.a365.core.guardrail_details import GuardrailDetails
from microsoft.opentelemetry.a365.core.guardrail_finding import GuardrailFinding
from microsoft.opentelemetry.a365.core.guardrail_risk_severity import GuardrailRiskSeverity
from microsoft.opentelemetry.a365.core.guardrail_target_type import GuardrailTargetType
from microsoft.opentelemetry.a365.core.models.user_details import UserDetails
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from microsoft.opentelemetry.a365.core.request import Request
from microsoft.opentelemetry.a365.core.span_details import SpanDetails


@patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"})
class TestApplyGuardrailScope(unittest.TestCase):
    """Tests for ApplyGuardrailScope."""

    def setUp(self):
        """Set up a real TracerProvider so spans are recorded."""
        self._provider = TracerProvider()
        trace.set_tracer_provider(self._provider)
        # Reset the cached tracer so the scope picks up the new provider
        OpenTelemetryScope._tracer = None

    def tearDown(self):
        self._provider.shutdown()
        OpenTelemetryScope._tracer = None

    def _make_agent_details(self):
        return AgentDetails(
            agent_id="agent-123",
            agent_name="Test Agent",
            tenant_id="tenant-456",
        )

    def _make_guardrail_details(self, **kwargs):
        defaults = {
            "target_type": GuardrailTargetType.LLM_INPUT,
            "decision_type": GuardrailDecisionType.ALLOW,
            "guardian_name": "Azure Content Safety",
        }
        defaults.update(kwargs)
        return GuardrailDetails(**defaults)

    def test_span_name_with_guardian_name(self):
        """Span name includes guardian name and target type."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            self.assertIsNotNone(scope._span)
            self.assertEqual(scope._span.name, "apply_guardrail Azure Content Safety llm_input")
        finally:
            scope.dispose()

    def test_span_name_without_guardian_name(self):
        """Span name falls back to target type only when no guardian name."""
        details = self._make_guardrail_details(guardian_name=None)
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            self.assertIsNotNone(scope._span)
            self.assertEqual(scope._span.name, "apply_guardrail llm_input")
        finally:
            scope.dispose()

    def test_span_kind_defaults_to_internal(self):
        """Span kind defaults to INTERNAL."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            self.assertIsNotNone(scope._span)
            self.assertEqual(scope._span.kind, SpanKind.INTERNAL)
        finally:
            scope.dispose()

    def test_operation_name_attribute(self):
        """Span has gen_ai.operation.name = 'apply_guardrail'."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[GEN_AI_OPERATION_NAME_KEY], APPLY_GUARDRAIL_OPERATION_NAME)
        finally:
            scope.dispose()

    def test_guardrail_attributes_set(self):
        """All guardrail-specific attributes are set on the span."""
        details = GuardrailDetails(
            target_type=GuardrailTargetType.TOOL_CALL,
            decision_type=GuardrailDecisionType.DENY,
            guardian_name="My Guardian",
            guardian_id="guardian-1",
            guardian_provider_name="azure.ai.content_safety",
            guardian_version="1.0.0",
            target_id="target-abc",
            decision_reason="Blocked",
            decision_code="BLOCKED_HATE",
            policy_id="pol-1",
            policy_name="Hate Speech Policy",
            policy_version="2.0",
            content_input_hash="sha256:abc123",
            content_modified=True,
            external_event_id="evt-999",
        )
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[GEN_AI_SECURITY_TARGET_TYPE_KEY], "tool_call")
            self.assertEqual(attrs[GEN_AI_SECURITY_DECISION_TYPE_KEY], "deny")
            self.assertEqual(attrs[GEN_AI_GUARDIAN_ID_KEY], "guardian-1")
            self.assertEqual(attrs[GEN_AI_GUARDIAN_NAME_KEY], "My Guardian")
            self.assertEqual(attrs[GEN_AI_GUARDIAN_PROVIDER_NAME_KEY], "azure.ai.content_safety")
            self.assertEqual(attrs[GEN_AI_GUARDIAN_VERSION_KEY], "1.0.0")
            self.assertEqual(attrs[GEN_AI_SECURITY_TARGET_ID_KEY], "target-abc")
            self.assertEqual(attrs[GEN_AI_SECURITY_DECISION_REASON_KEY], "Blocked")
            self.assertEqual(attrs[GEN_AI_SECURITY_DECISION_CODE_KEY], "BLOCKED_HATE")
            self.assertEqual(attrs[GEN_AI_SECURITY_POLICY_ID_KEY], "pol-1")
            self.assertEqual(attrs[GEN_AI_SECURITY_POLICY_NAME_KEY], "Hate Speech Policy")
            self.assertEqual(attrs[GEN_AI_SECURITY_POLICY_VERSION_KEY], "2.0")
            self.assertEqual(attrs[GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY], "sha256:abc123")
            self.assertEqual(attrs[GEN_AI_SECURITY_CONTENT_MODIFIED_KEY], True)
            self.assertEqual(attrs[GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY], "evt-999")
        finally:
            scope.dispose()

    def test_request_context_attributes(self):
        """Request context sets conversation_id and channel attributes."""
        details = self._make_guardrail_details()
        request = Request(
            conversation_id="conv-1",
            channel=Channel(name="teams", link="https://teams.example.com/conv-1"),
        )
        scope = ApplyGuardrailScope.start(details, self._make_agent_details(), request=request)
        try:
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[GEN_AI_CONVERSATION_ID_KEY], "conv-1")
            self.assertEqual(attrs[CHANNEL_NAME_KEY], "teams")
            self.assertEqual(attrs[CHANNEL_LINK_KEY], "https://teams.example.com/conv-1")
        finally:
            scope.dispose()

    def test_user_details_attributes(self):
        """User details are set on the span."""
        details = self._make_guardrail_details()
        user = UserDetails(user_id="user-1", user_email="user@example.com", user_name="Test User")
        scope = ApplyGuardrailScope.start(details, self._make_agent_details(), user_details=user)
        try:
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[USER_ID_KEY], "user-1")
            self.assertEqual(attrs[USER_EMAIL_KEY], "user@example.com")
            self.assertEqual(attrs[USER_NAME_KEY], "Test User")
        finally:
            scope.dispose()

    def test_record_decision_updates_attributes(self):
        """record_decision updates the decision type and reason."""
        details = self._make_guardrail_details(decision_type=GuardrailDecisionType.ALLOW)
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            scope.record_decision(GuardrailDecisionType.DENY, "Content blocked")
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[GEN_AI_SECURITY_DECISION_TYPE_KEY], "deny")
            self.assertEqual(attrs[GEN_AI_SECURITY_DECISION_REASON_KEY], "Content blocked")
        finally:
            scope.dispose()

    def test_record_content_output(self):
        """record_content_output sets the output value attribute."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            scope.record_content_output("sanitized output")
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY], "sanitized output")
        finally:
            scope.dispose()

    def test_record_content_input(self):
        """record_content_input sets the input value attribute."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            scope.record_content_input("user message content")
            attrs = dict(scope._span.attributes)
            self.assertEqual(attrs[GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY], "user message content")
        finally:
            scope.dispose()

    def test_record_finding_adds_event(self):
        """record_finding adds a security finding event to the span."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            finding = GuardrailFinding(
                risk_category="hate_speech",
                risk_severity=GuardrailRiskSeverity.HIGH,
                risk_score=0.95,
                risk_metadata=["token_index:42"],
                policy_decision_type=GuardrailDecisionType.DENY,
                policy_id="pol-1",
                policy_name="Hate Policy",
                policy_version="1.0",
            )
            scope.record_finding(finding)

            events = scope._span.events
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.name, GEN_AI_SECURITY_FINDING_EVENT_NAME)
            event_attrs = dict(event.attributes)
            self.assertEqual(event_attrs[GEN_AI_SECURITY_RISK_CATEGORY_KEY], "hate_speech")
            self.assertEqual(event_attrs[GEN_AI_SECURITY_RISK_SEVERITY_KEY], "high")
            self.assertAlmostEqual(event_attrs[GEN_AI_SECURITY_RISK_SCORE_KEY], 0.95)
            self.assertEqual(event_attrs[GEN_AI_SECURITY_RISK_METADATA_KEY], ("token_index:42",))
            self.assertEqual(event_attrs[GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY], "deny")
            self.assertEqual(event_attrs[GEN_AI_SECURITY_POLICY_ID_KEY], "pol-1")
            self.assertEqual(event_attrs[GEN_AI_SECURITY_POLICY_NAME_KEY], "Hate Policy")
            self.assertEqual(event_attrs[GEN_AI_SECURITY_POLICY_VERSION_KEY], "1.0")
        finally:
            scope.dispose()

    def test_record_multiple_findings(self):
        """Multiple findings can be recorded on a single span."""
        details = self._make_guardrail_details()
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            scope.record_finding(GuardrailFinding("pii", GuardrailRiskSeverity.MEDIUM))
            scope.record_finding(GuardrailFinding("jailbreak", GuardrailRiskSeverity.CRITICAL))

            events = scope._span.events
            self.assertEqual(len(events), 2)
            self.assertEqual(dict(events[0].attributes)[GEN_AI_SECURITY_RISK_CATEGORY_KEY], "pii")
            self.assertEqual(dict(events[1].attributes)[GEN_AI_SECURITY_RISK_CATEGORY_KEY], "jailbreak")
        finally:
            scope.dispose()

    def test_context_manager_usage(self):
        """Scope works as a context manager."""
        details = self._make_guardrail_details()
        with ApplyGuardrailScope.start(details, self._make_agent_details()) as scope:
            self.assertIsNotNone(scope._span)
            scope.record_decision(GuardrailDecisionType.ALLOW)
        # Span should be ended after context exit
        self.assertTrue(scope._has_ended)

    def test_optional_fields_not_set_when_none(self):
        """Optional None fields are not set as attributes."""
        details = GuardrailDetails(
            target_type=GuardrailTargetType.LLM_INPUT,
            decision_type=GuardrailDecisionType.ALLOW,
        )
        scope = ApplyGuardrailScope.start(details, self._make_agent_details())
        try:
            attrs = dict(scope._span.attributes)
            self.assertNotIn(GEN_AI_GUARDIAN_ID_KEY, attrs)
            self.assertNotIn(GEN_AI_GUARDIAN_NAME_KEY, attrs)
            self.assertNotIn(GEN_AI_GUARDIAN_PROVIDER_NAME_KEY, attrs)
            self.assertNotIn(GEN_AI_SECURITY_POLICY_ID_KEY, attrs)
            self.assertNotIn(GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY, attrs)
            self.assertNotIn(GEN_AI_SECURITY_CONTENT_MODIFIED_KEY, attrs)
            self.assertNotIn(GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY, attrs)
        finally:
            scope.dispose()


class TestGuardrailExporterEligibility(unittest.TestCase):
    """Tests that apply_guardrail spans are eligible for export."""

    def test_apply_guardrail_in_operation_names(self):
        """apply_guardrail is in the exporter operation name allowlist."""
        self.assertIn(APPLY_GUARDRAIL_OPERATION_NAME, GEN_AI_OPERATION_NAMES)

    def test_filter_partition_includes_guardrail_spans(self):
        """filter_and_partition_by_identity includes apply_guardrail spans."""
        span = MagicMock()
        span.attributes = {
            "gen_ai.operation.name": "apply_guardrail",
            "microsoft.tenant.id": "tenant-1",
            "gen_ai.agent.id": "agent-1",
        }

        groups = filter_and_partition_by_identity([span])
        self.assertIn(("tenant-1", "agent-1"), groups)
        self.assertEqual(len(groups[("tenant-1", "agent-1")]), 1)

    def test_filter_partition_excludes_non_eligible_spans(self):
        """Non-eligible operation names are filtered out."""
        guardrail_span = MagicMock()
        guardrail_span.attributes = {
            "gen_ai.operation.name": "apply_guardrail",
            "microsoft.tenant.id": "tenant-1",
            "gen_ai.agent.id": "agent-1",
        }
        http_span = MagicMock()
        http_span.attributes = {
            "gen_ai.operation.name": "http_request",
            "microsoft.tenant.id": "tenant-1",
            "gen_ai.agent.id": "agent-1",
        }

        groups = filter_and_partition_by_identity([guardrail_span, http_span])
        spans_in_group = groups[("tenant-1", "agent-1")]
        self.assertEqual(len(spans_in_group), 1)
        self.assertEqual(spans_in_group[0], guardrail_span)


class TestGuardrailDataClasses(unittest.TestCase):
    """Tests for guardrail data class constants."""

    def test_decision_type_values(self):
        self.assertEqual(GuardrailDecisionType.ALLOW, "allow")
        self.assertEqual(GuardrailDecisionType.AUDIT, "audit")
        self.assertEqual(GuardrailDecisionType.DENY, "deny")
        self.assertEqual(GuardrailDecisionType.MODIFY, "modify")
        self.assertEqual(GuardrailDecisionType.WARN, "warn")

    def test_risk_severity_values(self):
        self.assertEqual(GuardrailRiskSeverity.NONE, "none")
        self.assertEqual(GuardrailRiskSeverity.LOW, "low")
        self.assertEqual(GuardrailRiskSeverity.MEDIUM, "medium")
        self.assertEqual(GuardrailRiskSeverity.HIGH, "high")
        self.assertEqual(GuardrailRiskSeverity.CRITICAL, "critical")

    def test_target_type_values(self):
        self.assertEqual(GuardrailTargetType.LLM_INPUT, "llm_input")
        self.assertEqual(GuardrailTargetType.LLM_OUTPUT, "llm_output")
        self.assertEqual(GuardrailTargetType.TOOL_CALL, "tool_call")
        self.assertEqual(GuardrailTargetType.TOOL_DEFINITION, "tool_definition")
        self.assertEqual(GuardrailTargetType.MEMORY_STORE, "memory_store")
        self.assertEqual(GuardrailTargetType.MEMORY_RETRIEVE, "memory_retrieve")
        self.assertEqual(GuardrailTargetType.KNOWLEDGE_QUERY, "knowledge_query")
        self.assertEqual(GuardrailTargetType.KNOWLEDGE_RESULT, "knowledge_result")
        self.assertEqual(GuardrailTargetType.MESSAGE, "message")

    def test_guardrail_details_required_fields(self):
        details = GuardrailDetails(target_type="llm_input", decision_type="allow")
        self.assertEqual(details.target_type, "llm_input")
        self.assertEqual(details.decision_type, "allow")
        self.assertIsNone(details.guardian_name)

    def test_guardrail_finding_required_fields(self):
        finding = GuardrailFinding(risk_category="pii", risk_severity="high")
        self.assertEqual(finding.risk_category, "pii")
        self.assertEqual(finding.risk_severity, "high")
        self.assertIsNone(finding.risk_score)
        self.assertIsNone(finding.risk_metadata)


@patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "false"})
class TestApplyGuardrailScopeDisabled(unittest.TestCase):
    """Tests that scope is a no-op when telemetry is disabled."""

    def test_no_span_when_disabled(self):
        """No span is created when telemetry is disabled."""
        # Reset the enabled_by_distro flag
        OpenTelemetryScope._enabled_by_distro = False
        details = GuardrailDetails(
            target_type=GuardrailTargetType.LLM_INPUT,
            decision_type=GuardrailDecisionType.ALLOW,
        )
        agent_details = AgentDetails(agent_id="a", tenant_id="t")
        scope = ApplyGuardrailScope.start(details, agent_details)
        try:
            self.assertIsNone(scope._span)
            # These should not raise
            scope.record_decision(GuardrailDecisionType.DENY, "blocked")
            scope.record_content_output("output")
            scope.record_content_input("input")
            scope.record_finding(GuardrailFinding("pii", "high"))
        finally:
            scope.dispose()


if __name__ == "__main__":
    unittest.main()
