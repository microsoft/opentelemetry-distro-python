# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests verifying that the LangChain tracer correctly propagates
main-agent attributes when used with GenAIMainAgentSpanProcessor.

Attribute key compatibility tests verify that the LangChain tracer's
OTel semconv re-exports resolve to the same strings as the a365 constants.

End-to-end tests run the actual LangChain tracer with a real TracerProvider
and GenAIMainAgentSpanProcessor.

Generic SDK-level propagation tests (not LangChain-specific) live in
``tests/genai/main_agent/test_sdk_propagation.py``.
"""

import datetime
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("langchain_core")

from opentelemetry import trace as trace_api  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

# LangChain tracer attribute keys (from OTel semconv re-exports)
from microsoft.opentelemetry._genai._langchain._utils import (  # noqa: E402
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)

# Main agent constants
from microsoft.opentelemetry._constants import (  # noqa: E402
    GEN_AI_MAIN_AGENT_ID_KEY,
    GEN_AI_MAIN_AGENT_NAME_KEY,
)

# a365 constants used by the processor
from microsoft.opentelemetry.a365.core.constants import (  # noqa: E402
    GEN_AI_AGENT_ID_KEY as A365_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY as A365_AGENT_NAME_KEY,
    GEN_AI_AGENT_VERSION_KEY as A365_AGENT_VERSION_KEY,
    GEN_AI_CONVERSATION_ID_KEY as A365_CONVERSATION_ID_KEY,
    GEN_AI_OPERATION_NAME_KEY as A365_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME as A365_INVOKE_AGENT,
)

from microsoft.opentelemetry._genai.main_agent._processor import (  # noqa: E402
    GenAIMainAgentSpanProcessor,
)


# ---------------------------------------------------------------------------
# Attribute key compatibility
# ---------------------------------------------------------------------------


class TestAttributeKeyCompatibility(unittest.TestCase):
    """Verify that the LangChain tracer's OTel semconv re-exports resolve
    to the same string values as the a365 constants used by the processor."""

    def test_agent_name_key_matches(self):
        self.assertEqual(GEN_AI_AGENT_NAME_KEY, A365_AGENT_NAME_KEY)

    def test_agent_id_key_matches(self):
        self.assertEqual(GEN_AI_AGENT_ID_KEY, A365_AGENT_ID_KEY)

    def test_agent_version_key_matches(self):
        self.assertEqual(GEN_AI_AGENT_VERSION_KEY, A365_AGENT_VERSION_KEY)

    def test_conversation_id_key_matches(self):
        self.assertEqual(GEN_AI_CONVERSATION_ID_KEY, A365_CONVERSATION_ID_KEY)

    def test_operation_name_key_matches(self):
        self.assertEqual(GEN_AI_OPERATION_NAME_KEY, A365_OPERATION_NAME_KEY)

    def test_invoke_agent_value_matches(self):
        self.assertEqual(INVOKE_AGENT_OPERATION_NAME, A365_INVOKE_AGENT)


# ---------------------------------------------------------------------------
# End-to-end: actual LangChain tracer + processor
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2024, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_NOW_END = datetime.datetime(2024, 6, 1, 12, 0, 1, tzinfo=datetime.timezone.utc)


def _make_run(**kwargs):
    """Create a minimal mock Run for LangChain tracer tests."""
    run = MagicMock()
    run.id = kwargs.get("id", uuid4())
    run.name = kwargs.get("name", "test_run")
    run.run_type = kwargs.get("run_type", "chain")
    run.inputs = kwargs.get("inputs", None)
    run.outputs = kwargs.get("outputs", None)
    run.extra = kwargs.get("extra", None)
    run.serialized = kwargs.get("serialized", None)
    run.error = kwargs.get("error", None)
    run.parent_run_id = kwargs.get("parent_run_id", None)
    run.start_time = kwargs.get("start_time", _NOW)
    run.end_time = kwargs.get("end_time", _NOW_END)
    return run


class TestLangChainTracerMainAgentIntegration(unittest.TestCase):
    """End-to-end: runs the actual LangChain tracer with
    GenAIMainAgentSpanProcessor to verify propagation works.
    """

    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(GenAIMainAgentSpanProcessor())
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.otel_tracer = self.provider.get_tracer("test-langchain")

    def tearDown(self):
        self.provider.shutdown()

    def _get_exported_spans(self):
        return list(self.exporter.get_finished_spans())

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_tracer_agent_run_propagates_main_agent_to_llm_child(self, mock_ctx):
        """Full LangChain tracer flow: agent run -> LLM child run.
        Verifies main_agent attrs appear on the LLM span."""
        from microsoft.opentelemetry._genai._langchain._tracer import LangChainTracer

        mock_ctx.get_value.return_value = None
        mock_ctx.Context.return_value = trace_api.set_span_in_context(trace_api.INVALID_SPAN)

        tracer = LangChainTracer(
            self.otel_tracer,
            separate_trace_from_runtime_context=True,
            agent_config={
                "agent_name": "TravelBot",
                "agent_id": "agent-123",
                "agent_version": "2.0",
            },
        )

        # Start agent run (wrapper + inner spans created)
        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        # Start LLM run (child of agent)
        llm_run = _make_run(
            run_type="llm",
            name="gpt-4",
            parent_run_id=agent_run.id,
            outputs={"llm_output": {"model_name": "gpt-4"}, "generations": []},
            extra=None,
            inputs=None,
        )
        tracer._start_trace(llm_run)

        # End LLM run, then agent run
        tracer._end_trace(llm_run)
        tracer._end_trace(agent_run)

        exported = self._get_exported_spans()
        self.assertGreaterEqual(len(exported), 2)

        # Find the LLM span
        llm_spans = [s for s in exported if "gpt-4" in s.name]
        self.assertTrue(len(llm_spans) > 0, f"Expected LLM span, got: {[s.name for s in exported]}")
        llm_span = llm_spans[0]

        self.assertEqual(
            llm_span.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY),
            "TravelBot",
            f"LLM span should have main_agent.name. Attrs: {dict(llm_span.attributes)}",
        )
        self.assertEqual(
            llm_span.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY),
            "agent-123",
            f"LLM span should have main_agent.id. Attrs: {dict(llm_span.attributes)}",
        )

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_tracer_agent_run_propagates_main_agent_to_tool_child(self, mock_ctx):
        """Full LangChain tracer flow: agent run -> tool child run.
        Verifies main_agent attrs appear on the tool span."""
        from microsoft.opentelemetry._genai._langchain._tracer import LangChainTracer

        mock_ctx.get_value.return_value = None
        mock_ctx.Context.return_value = trace_api.set_span_in_context(trace_api.INVALID_SPAN)

        tracer = LangChainTracer(
            self.otel_tracer,
            separate_trace_from_runtime_context=True,
            agent_config={
                "agent_name": "TravelBot",
                "agent_id": "agent-123",
            },
        )

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        tool_run = _make_run(
            run_type="tool",
            name="get_weather",
            parent_run_id=agent_run.id,
            outputs={"output": "72F"},
            serialized={"name": "get_weather", "description": "Weather tool"},
        )
        tracer._start_trace(tool_run)

        tracer._end_trace(tool_run)
        tracer._end_trace(agent_run)

        exported = self._get_exported_spans()
        tool_spans = [s for s in exported if "get_weather" in s.name]
        self.assertTrue(len(tool_spans) > 0, f"Expected tool span, got: {[s.name for s in exported]}")
        tool_span = tool_spans[0]

        self.assertEqual(
            tool_span.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY),
            "TravelBot",
            f"Tool span should have main_agent.name. Attrs: {dict(tool_span.attributes)}",
        )
        self.assertEqual(
            tool_span.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY),
            "agent-123",
            f"Tool span should have main_agent.id. Attrs: {dict(tool_span.attributes)}",
        )


if __name__ == "__main__":
    unittest.main()
