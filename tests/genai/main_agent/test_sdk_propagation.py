# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Real-SDK tests for GenAIMainAgentSpanProcessor propagation.

Uses a real TracerProvider + InMemorySpanExporter to verify that
``microsoft.gen_ai.main_agent.*`` attributes propagate through span
hierarchies for all GenAI span patterns (invoke_agent → chat, tool, etc.).

These tests catch timing issues (attributes set after child span creation)
and on_end limitations that unit tests with mocks cannot detect.
"""

import unittest

from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from microsoft.opentelemetry._constants import (
    GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY,
    GEN_AI_MAIN_AGENT_ID_KEY,
    GEN_AI_MAIN_AGENT_NAME_KEY,
    GEN_AI_MAIN_AGENT_VERSION_KEY,
)
from microsoft.opentelemetry._genai.main_agent._processor import (
    GenAIMainAgentSpanProcessor,
)
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)


class TestSDKPropagation(unittest.TestCase):
    """Verifies main-agent attribute propagation using real OTel SDK spans.

    Each test simulates a different GenAI span hierarchy pattern:
    invoke_agent → chat, invoke_agent → execute_tool, multi-agent, etc.
    """

    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        # Main-agent processor FIRST so on_start enriches before export
        self.provider.add_span_processor(GenAIMainAgentSpanProcessor())
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("test")

    def tearDown(self):
        self.provider.shutdown()

    def _get_exported_spans(self):
        return {s.name: s for s in self.exporter.get_finished_spans()}

    # ---- invoke_agent → chat -------------------------------------------------

    def test_invoke_agent_propagates_to_chat_span(self):
        """invoke_agent (with gen_ai.agent.*) → chat child:
        child must have microsoft.gen_ai.main_agent.* attrs."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        agent_span.set_attribute(GEN_AI_AGENT_ID_KEY, "agent-1")
        agent_span.set_attribute(GEN_AI_AGENT_VERSION_KEY, "2.0")
        agent_span.set_attribute(GEN_AI_CONVERSATION_ID_KEY, "conv-1")

        chat_ctx = trace_api.set_span_in_context(agent_span)
        chat_span = self.tracer.start_span("chat gpt-4", context=chat_ctx)
        chat_span.end()
        agent_span.end()

        spans = self._get_exported_spans()
        chat = spans["chat gpt-4"]

        self.assertEqual(chat.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(chat.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "agent-1")
        self.assertEqual(chat.attributes.get(GEN_AI_MAIN_AGENT_VERSION_KEY), "2.0")
        self.assertEqual(chat.attributes.get(GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY), "conv-1")

    # ---- invoke_agent → execute_tool -----------------------------------------

    def test_invoke_agent_propagates_to_tool_span(self):
        """invoke_agent → execute_tool child:
        tool span must have microsoft.gen_ai.main_agent.* attrs."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        agent_span.set_attribute(GEN_AI_AGENT_ID_KEY, "agent-1")

        tool_ctx = trace_api.set_span_in_context(agent_span)
        tool_span = self.tracer.start_span("execute_tool get_weather", context=tool_ctx)
        tool_span.end()
        agent_span.end()

        spans = self._get_exported_spans()
        tool = spans["execute_tool get_weather"]

        self.assertEqual(tool.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(tool.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "agent-1")

    # ---- invoke_agent → wrapper → inner → chat (LangChain two-span pattern) --

    def test_two_span_wrapper_propagates_through_inner_to_chat(self):
        """Simulates the LangChain two-span pattern:
        wrapper_span (agent attrs) → inner_span → chat_span.
        main_agent attrs must propagate through the entire chain."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        wrapper = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        wrapper.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        wrapper.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        wrapper.set_attribute(GEN_AI_AGENT_ID_KEY, "agent-1")

        inner_ctx = trace_api.set_span_in_context(wrapper)
        inner = self.tracer.start_span("invoke_agent LangGraph", context=inner_ctx)

        chat_ctx = trace_api.set_span_in_context(inner)
        chat = self.tracer.start_span("chat gpt-4", context=chat_ctx)
        chat.end()
        inner.end()
        wrapper.end()

        spans = self._get_exported_spans()

        # Inner span gets attrs from wrapper via fallback (gen_ai.agent.*)
        self.assertEqual(spans["invoke_agent LangGraph"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(spans["invoke_agent LangGraph"].attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "agent-1")
        # Chat span gets attrs from inner via primary (microsoft.gen_ai.main_agent.*)
        self.assertEqual(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "agent-1")

    # ---- Multi-agent: main_agent → sub_agent → chat -------------------------

    def test_multi_agent_preserves_main_agent_over_sub_agent(self):
        """main_agent → sub_agent → chat:
        sub_agent has its own gen_ai.agent.* but the MAIN agent's
        microsoft.gen_ai.main_agent.* must be preserved on grandchild."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        main_span = self.tracer.start_span("invoke_agent MainBot", context=root_ctx)
        main_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        main_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "MainBot")
        main_span.set_attribute(GEN_AI_AGENT_ID_KEY, "main-1")

        sub_ctx = trace_api.set_span_in_context(main_span)
        sub_span = self.tracer.start_span("invoke_agent SubBot", context=sub_ctx)
        sub_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        sub_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "SubBot")
        sub_span.set_attribute(GEN_AI_AGENT_ID_KEY, "sub-1")

        chat_ctx = trace_api.set_span_in_context(sub_span)
        chat = self.tracer.start_span("chat gpt-4", context=chat_ctx)
        chat.end()
        sub_span.end()
        main_span.end()

        spans = self._get_exported_spans()

        # Sub-agent should get MainBot's attrs (primary from on_start propagation)
        self.assertEqual(spans["invoke_agent SubBot"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "MainBot")
        self.assertEqual(spans["invoke_agent SubBot"].attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "main-1")
        # Chat should also preserve MainBot (propagated through sub-agent)
        self.assertEqual(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "MainBot")
        self.assertEqual(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "main-1")

    # ---- invoke_agent → chat + tool siblings ---------------------------------

    def test_propagation_to_sibling_spans(self):
        """invoke_agent → [chat, tool]: both siblings get main_agent attrs."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")

        child_ctx = trace_api.set_span_in_context(agent_span)
        chat = self.tracer.start_span("chat gpt-4", context=child_ctx)
        chat.end()
        tool = self.tracer.start_span("execute_tool search", context=child_ctx)
        tool.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self.assertEqual(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(spans["execute_tool search"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")

    # ---- Non-agent parent → child: no propagation ----------------------------

    def test_non_agent_parent_does_not_propagate(self):
        """A chat span without gen_ai.agent.* should not inject main_agent attrs."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        parent = self.tracer.start_span("chat gpt-4", context=root_ctx)
        parent.set_attribute("http.method", "POST")

        child_ctx = trace_api.set_span_in_context(parent)
        child = self.tracer.start_span("some_child", context=child_ctx)
        child.end()
        parent.end()

        spans = self._get_exported_spans()
        self.assertIsNone(spans["some_child"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY))

    # ---- Timing: attributes set AFTER child creation → broken ----------------

    def test_attrs_set_after_child_creation_breaks_propagation(self):
        """If agent attributes are set AFTER creating the child span,
        on_start cannot propagate them. This is the timing bug."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)

        # BUG: create child BEFORE setting attributes on parent
        child_ctx = trace_api.set_span_in_context(agent_span)
        child = self.tracer.start_span("chat gpt-4", context=child_ctx)

        # Attributes set AFTER child creation → on_start already fired
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")

        child.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self.assertIsNone(
            spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY),
            "on_start fired before attrs were set — propagation must fail",
        )

    # ---- Partial attributes: only name set -----------------------------------

    def test_partial_attributes_propagate(self):
        """Only agent_name on parent → only main_agent.name on child."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent Bot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "Bot")

        child_ctx = trace_api.set_span_in_context(agent_span)
        child = self.tracer.start_span("chat gpt-4", context=child_ctx)
        child.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self.assertEqual(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "Bot")
        self.assertIsNone(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_ID_KEY))


if __name__ == "__main__":
    unittest.main()
