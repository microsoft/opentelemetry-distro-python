# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from unittest.mock import patch

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
                    resources=[ToolCallResource(resource_id="file-1")],
                ),
            ),
            self._make_agent_details(),
        )
        try:
            attrs = dict(scope._span.attributes)
            payload = json.loads(attrs[GEN_AI_TOOL_ARGS_KEY])

            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["action"], "read")
            self.assertEqual(payload["resources"], [{"id": "file-1"}])
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
                    outcome=ToolCallResultOutcome(status=ToolCallOutcomeStatus.SUCCESS),
                    data={"count": 0},
                )
            )
            attrs = dict(scope._span.attributes)
            payload = json.loads(attrs[GEN_AI_TOOL_CALL_RESULT_KEY])

            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["outcome"], {"status": "success"})
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


@patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "false"})
class TestExecuteToolScopeWithTelemetryDisabled(unittest.TestCase):
    def setUp(self):
        OpenTelemetryScope._tracer = None

    def tearDown(self):
        OpenTelemetryScope._tracer = None

    def test_unserializable_typed_payloads_are_safe_when_telemetry_is_disabled(self):
        result = ExecuteToolCallResult()
        result.extension_data["self"] = result

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

        self.assertIsNone(scope._span)
