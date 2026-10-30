# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from microsoft.opentelemetry.a365.core.agent_details import AgentDetails
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_TOOL_ARGS_KEY,
    GEN_AI_TOOL_CALL_RESULT_KEY,
)
from microsoft.opentelemetry.a365.core.execute_tool_scope import ExecuteToolScope
from microsoft.opentelemetry.a365.core.models.tool_call_schema import (
    TOOL_CALL_SERIALIZATION_ERROR_JSON,
    ExecuteToolCallArguments,
    ExecuteToolCallResult,
    ToolCallAction,
    ToolCallOutcomeStatus,
    ToolCallResource,
    ToolCallResultOutcome,
)
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from microsoft.opentelemetry.a365.core.request import Request
from microsoft.opentelemetry.a365.core.tool_call_details import ToolCallDetails


@patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"})
class TestExecuteToolScope(unittest.TestCase):
    def setUp(self):
        self._provider = TracerProvider()
        trace.set_tracer_provider(self._provider)
        OpenTelemetryScope._tracer = None

    def tearDown(self):
        self._provider.shutdown()
        OpenTelemetryScope._tracer = None

    def _make_agent_details(self):
        return AgentDetails(agent_id="agent-1")

    def test_typed_arguments_include_schema_version(self):
        scope = ExecuteToolScope.start(
            Request(conversation_id="conversation-1"),
            ToolCallDetails(
                tool_name="read_file",
                arguments=ExecuteToolCallArguments(
                    action=ToolCallAction.READ,
                    resources=[
                        ToolCallResource(
                            resource_id="file-1",
                            extension_data={"tenant_id": "tenant-123"},
                        )
                    ],
                    extension_data={"provider_trace_id": "trace-789"},
                ),
            ),
            self._make_agent_details(),
        )
        try:
            attrs = dict(scope._span.attributes)
            payload = json.loads(attrs[GEN_AI_TOOL_ARGS_KEY])

            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["action"], "read")
            self.assertEqual(payload["metadata"], {"provider_trace_id": "trace-789"})
            self.assertEqual(
                payload["resources"],
                [{"id": "file-1", "metadata": {"tenant_id": "tenant-123"}}],
            )
        finally:
            scope.dispose()

    def test_typed_result_include_schema_version(self):
        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file"),
            self._make_agent_details(),
        )
        try:
            scope.record_response(
                ExecuteToolCallResult(
                    outcome=ToolCallResultOutcome(
                        status=ToolCallOutcomeStatus.SUCCESS,
                        extension_data={"provider_status": "accepted"},
                    ),
                    data={"count": 0},
                    extension_data={"provider_trace_id": "trace-789"},
                )
            )
            attrs = dict(scope._span.attributes)
            payload = json.loads(attrs[GEN_AI_TOOL_CALL_RESULT_KEY])

            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["metadata"], {"provider_trace_id": "trace-789"})
            self.assertEqual(
                payload["outcome"],
                {
                    "status": "success",
                    "metadata": {"provider_status": "accepted"},
                },
            )
            self.assertEqual(payload["data"], {"count": 0})
        finally:
            scope.dispose()

    def test_raw_arguments_and_results_are_unchanged(self):
        arguments = {"existing": True}
        result = {"ok": False}
        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file", arguments=arguments),
            self._make_agent_details(),
        )
        try:
            scope.record_response(result)
            attrs = dict(scope._span.attributes)

            self.assertEqual(attrs[GEN_AI_TOOL_ARGS_KEY], json.dumps(arguments))
            self.assertEqual(attrs[GEN_AI_TOOL_CALL_RESULT_KEY], json.dumps(result))
        finally:
            scope.dispose()

    def test_raw_argument_and_result_strings_are_unchanged(self):
        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file", arguments="raw arguments"),
            self._make_agent_details(),
        )
        try:
            scope.record_response("raw result")
            attrs = dict(scope._span.attributes)

            self.assertEqual(attrs[GEN_AI_TOOL_ARGS_KEY], "raw arguments")
            self.assertEqual(attrs[GEN_AI_TOOL_CALL_RESULT_KEY], "raw result")
        finally:
            scope.dispose()

    def test_unserializable_typed_arguments_record_diagnostic_payload(self):
        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(
                tool_name="read_file",
                arguments=ExecuteToolCallArguments(extension_data={"bad": object()}),
            ),
            self._make_agent_details(),
        )
        try:
            attrs = dict(scope._span.attributes)

            self.assertEqual(attrs[GEN_AI_TOOL_ARGS_KEY], TOOL_CALL_SERIALIZATION_ERROR_JSON)
        finally:
            scope.dispose()

    def test_unserializable_typed_result_records_diagnostic_payload(self):
        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file"),
            self._make_agent_details(),
        )
        try:
            result = ExecuteToolCallResult()
            result.extension_data["self"] = result
            scope.record_response(result)
            attrs = dict(scope._span.attributes)

            self.assertEqual(attrs[GEN_AI_TOOL_CALL_RESULT_KEY], TOOL_CALL_SERIALIZATION_ERROR_JSON)
        finally:
            scope.dispose()

    def test_none_result_omits_result_tag(self):
        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file"),
            self._make_agent_details(),
        )
        try:
            scope.record_response(None)

            self.assertNotIn(GEN_AI_TOOL_CALL_RESULT_KEY, dict(scope._span.attributes))
        finally:
            scope.dispose()

    def test_unserializable_payloads_do_not_orphan_the_span(self):
        with ExecuteToolScope.start(
            Request(),
            ToolCallDetails(
                tool_name="read_file",
                arguments=ExecuteToolCallArguments(extension_data={"bad": object()}),
            ),
            self._make_agent_details(),
        ) as scope:
            span = scope._span
            self.assertTrue(span.is_recording())
            scope.record_response(ExecuteToolCallResult(data={"bad": float("nan")}))

        attrs = dict(span.attributes)
        self.assertIsNotNone(span.end_time)
        self.assertFalse(span.is_recording())
        self.assertEqual(attrs[GEN_AI_TOOL_ARGS_KEY], TOOL_CALL_SERIALIZATION_ERROR_JSON)
        self.assertEqual(attrs[GEN_AI_TOOL_CALL_RESULT_KEY], TOOL_CALL_SERIALIZATION_ERROR_JSON)

    def test_unserializable_raw_dict_payloads_do_not_orphan_the_span(self):
        cyclic_arguments: dict[str, object] = {}
        cyclic_arguments["self"] = cyclic_arguments
        cyclic_result: dict[str, object] = {}
        cyclic_result["self"] = cyclic_result

        with ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file", arguments=cyclic_arguments),
            self._make_agent_details(),
        ) as scope:
            span = scope._span
            scope.record_response(cyclic_result)

        attrs = dict(span.attributes)
        self.assertIsNotNone(span.end_time)
        self.assertEqual(attrs[GEN_AI_TOOL_ARGS_KEY], TOOL_CALL_SERIALIZATION_ERROR_JSON)
        self.assertEqual(attrs[GEN_AI_TOOL_CALL_RESULT_KEY], TOOL_CALL_SERIALIZATION_ERROR_JSON)


@patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "false"})
class TestExecuteToolScopeWithTelemetryDisabled(unittest.TestCase):
    def setUp(self):
        OpenTelemetryScope._tracer = None

    def tearDown(self):
        OpenTelemetryScope._tracer = None

    def test_unserializable_typed_payloads_are_safe_when_telemetry_is_disabled(self):
        result = ExecuteToolCallResult()
        result.extension_data["self"] = result
        cyclic_arguments: dict[str, object] = {}
        cyclic_arguments["self"] = cyclic_arguments

        scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(
                tool_name="read_file",
                arguments=ExecuteToolCallArguments(extension_data={"bad": object()}),
            ),
            AgentDetails(agent_id="agent-1"),
        )
        scope.record_response(result)
        scope.dispose()

        raw_scope = ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="read_file", arguments=cyclic_arguments),
            AgentDetails(agent_id="agent-1"),
        )
        raw_scope.record_response(cyclic_arguments)
        raw_scope.dispose()

        self.assertIsNone(scope._span)
        self.assertIsNone(raw_scope._span)


@pytest.fixture(name="transfer_tracer")
def _transfer_tracer(monkeypatch):
    provider = TracerProvider()
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setattr(ExecuteToolScope, "_tracer", provider.get_tracer("Agent365Sdk"))
    yield
    provider.shutdown()


@pytest.mark.parametrize("mode", ["RETURN_TO_CALLER", "PASS_CONTROL"])
@pytest.mark.parametrize("target_type", ["AGENT", "HUMAN", "WORKFLOW"])
def test_transfer_modes_and_target_types(transfer_tracer, mode, target_type):
    from microsoft.opentelemetry.a365.core import TransferDetails, TransferMode, TransferTargetType

    with ExecuteToolScope.start(
        Request(),
        ToolCallDetails(
            tool_name="handoff",
            transfer_details=TransferDetails(TransferMode[mode], TransferTargetType[target_type]),
        ),
        AgentDetails(agent_id="source-agent"),
    ) as scope:
        attrs = dict(scope._span.attributes)
        assert attrs["microsoft.a365.transfer.mode"] == mode.lower()
        assert attrs["microsoft.a365.transfer.target.type"] == target_type.lower()
        assert not any(key.startswith("microsoft.a365.transfer.target.agent.") for key in attrs)


def test_transfer_records_only_supported_target_fields_and_preserves_source(transfer_tracer):
    from microsoft.opentelemetry.a365.core import TransferDetails, TransferMode

    target = AgentDetails(
        agent_id="target-agent",
        agent_name="Target",
        agent_blueprint_id="target-blueprint",
        agent_platform_id="target-platform",
        agent_version="2",
        tenant_id="target-tenant",
        agentic_user_id="target-user",
        agentic_user_email="target@example.test",
        agent_description="not transferred",
    )
    with ExecuteToolScope.start(
        Request(),
        ToolCallDetails(
            tool_name="handoff",
            transfer_details=TransferDetails(TransferMode.PASS_CONTROL, target_agent_details=target),
        ),
        AgentDetails(agent_id="source-agent", agent_name="Source", tenant_id="source-tenant"),
    ) as scope:
        attrs = dict(scope._span.attributes)
        assert attrs["gen_ai.agent.id"] == "source-agent"
        assert attrs["gen_ai.agent.name"] == "Source"
        assert attrs["microsoft.tenant.id"] == "source-tenant"
        assert attrs["microsoft.a365.transfer.target.type"] == "agent"
        assert {
            key.removeprefix("microsoft.a365.transfer.target.agent."): value
            for key, value in attrs.items()
            if key.startswith("microsoft.a365.transfer.target.agent.")
        } == {
            "id": "target-agent",
            "name": "Target",
            "blueprint.id": "target-blueprint",
            "platform.id": "target-platform",
            "version": "2",
        }


@pytest.mark.parametrize("transfer_enabled", [False, True])
def test_transfer_attributes_follow_explicit_opt_in(transfer_tracer, transfer_enabled):
    from microsoft.opentelemetry.a365.core import TransferDetails, TransferMode

    details = TransferDetails(TransferMode.RETURN_TO_CALLER) if transfer_enabled else None
    with ExecuteToolScope.start(
        Request(), ToolCallDetails(tool_name="ordinary_tool", transfer_details=details), AgentDetails("source")
    ) as scope:
        attrs = dict(scope._span.attributes)
        assert any(key.startswith("microsoft.a365.transfer.") for key in attrs) == transfer_enabled


@pytest.mark.parametrize("target_type", ["HUMAN", "WORKFLOW"])
def test_transfer_rejects_agent_details_for_non_agent_targets(target_type):
    from microsoft.opentelemetry.a365.core import TransferDetails, TransferMode, TransferTargetType

    with pytest.raises(ValueError, match="agent"):
        TransferDetails(TransferMode.PASS_CONTROL, TransferTargetType[target_type], AgentDetails("target"))


@pytest.mark.parametrize("field", ["mode", "target_type"])
def test_transfer_rejects_untyped_enum_values(field):
    from microsoft.opentelemetry.a365.core import TransferDetails, TransferMode, TransferTargetType

    values = {"mode": TransferMode.PASS_CONTROL, "target_type": TransferTargetType.AGENT}
    values[field] = "invalid"
    with pytest.raises(TypeError, match=field):
        TransferDetails(**values)


def test_transfer_is_safe_with_telemetry_disabled(monkeypatch):
    from microsoft.opentelemetry.a365.core import TransferDetails, TransferMode

    monkeypatch.setenv("ENABLE_OBSERVABILITY", "false")
    with ExecuteToolScope.start(
        Request(),
        ToolCallDetails(tool_name="handoff", transfer_details=TransferDetails(TransferMode.PASS_CONTROL)),
        AgentDetails("source"),
    ) as scope:
        assert scope._span is None


@pytest.mark.parametrize(
    "url,host,port",
    [
        ("https://tools.example.test/api/search?q=weather", "tools.example.test", None),
        ("https://tools.example.test:8443/api", "tools.example.test", 8443),
        ("http://tools.example.test/api", "tools.example.test", 80),
        ("https://[::1]:8443/api", "::1", 8443),
    ],
)
def test_execute_tool_records_full_endpoint_url(monkeypatch, url, host, port):
    from microsoft.opentelemetry.a365.core import ServiceEndpoint

    provider = TracerProvider()
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setattr(ExecuteToolScope, "_tracer", provider.get_tracer("Agent365Sdk"))
    try:
        with ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="search", endpoint=ServiceEndpoint.from_url(url)),
            AgentDetails("agent"),
        ) as scope:
            attrs = dict(scope._span.attributes)
            assert attrs["url.full"] == url
            assert attrs["server.address"] == host
            if port is None:
                assert "server.port" not in attrs
            else:
                assert attrs["server.port"] == port
    finally:
        provider.shutdown()


def test_execute_tool_preserves_hostname_only_endpoints(monkeypatch):
    from microsoft.opentelemetry.a365.core import ServiceEndpoint

    provider = TracerProvider()
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setattr(ExecuteToolScope, "_tracer", provider.get_tracer("Agent365Sdk"))
    try:
        with ExecuteToolScope.start(
            Request(),
            ToolCallDetails(tool_name="search", endpoint=ServiceEndpoint("tools.example.test", 8443)),
            AgentDetails("agent"),
        ) as scope:
            attrs = dict(scope._span.attributes)
            assert attrs["server.address"] == "tools.example.test"
            assert attrs["server.port"] == 8443
            assert "url.full" not in attrs
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("", id="empty"),
        pytest.param(" \t\r\n", id="whitespace-only"),
        pytest.param("relative/path", id="relative-path"),
        pytest.param("//tools.example.test/api", id="missing-scheme"),
        pytest.param("https:///api", id="missing-host"),
        pytest.param("https://:8443/api", id="port-without-host"),
        pytest.param("https://[::1/api", id="malformed-ipv6"),
        pytest.param("https://tools.example.test:invalid/api", id="nonnumeric-port"),
        pytest.param("https://tools.example.test:-1/api", id="negative-port"),
        pytest.param("https://tools.example.test:65536/api", id="out-of-range-port"),
    ],
)
def test_service_endpoint_rejects_invalid_absolute_urls(url):
    from microsoft.opentelemetry.a365.core import ServiceEndpoint

    with pytest.raises(ValueError):
        ServiceEndpoint.from_url(url)
