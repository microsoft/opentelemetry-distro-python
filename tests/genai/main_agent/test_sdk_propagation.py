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
    GEN_AI_PROJECT_ID_KEYS,
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

    def test_attrs_set_after_child_creation_recovered_on_end(self):
        """If agent attributes are set AFTER creating the child span,
        on_start cannot propagate them — but on_end fallback re-reads
        from the (now enriched) parent and fills in the gap."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)

        # Create child BEFORE setting attributes on parent
        child_ctx = trace_api.set_span_in_context(agent_span)
        child = self.tracer.start_span("chat gpt-4", context=child_ctx)

        # Attributes set AFTER child creation → on_start already fired
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")

        child.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self.assertEqual(
            spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY),
            "TravelBot",
            "on_end fallback should recover propagation from the parent",
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

    # ---- On-end self-promotion for root invoke_agent -------------------------

    def test_root_invoke_agent_self_promotes_on_end(self):
        """A root invoke_agent span with no parent must self-promote
        its gen_ai.agent.* to microsoft.gen_ai.main_agent.* on end."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        agent.set_attribute(GEN_AI_AGENT_ID_KEY, "agent-1")
        agent.set_attribute(GEN_AI_AGENT_VERSION_KEY, "2.0")
        agent.set_attribute(GEN_AI_CONVERSATION_ID_KEY, "conv-1")
        agent.end()

        spans = self._get_exported_spans()
        exported = spans["invoke_agent TravelBot"]
        self.assertEqual(exported.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(exported.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "agent-1")
        self.assertEqual(exported.attributes.get(GEN_AI_MAIN_AGENT_VERSION_KEY), "2.0")
        self.assertEqual(exported.attributes.get(GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY), "conv-1")

    def test_nested_invoke_agent_does_not_self_promote(self):
        """A nested invoke_agent span enriched by on_start propagation
        must NOT self-promote (main_agent.* already set from parent)."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        main = self.tracer.start_span("invoke_agent MainBot", context=root_ctx)
        main.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        main.set_attribute(GEN_AI_AGENT_NAME_KEY, "MainBot")
        main.set_attribute(GEN_AI_AGENT_ID_KEY, "main-1")

        sub_ctx = trace_api.set_span_in_context(main)
        sub = self.tracer.start_span("invoke_agent SubBot", context=sub_ctx)
        sub.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        sub.set_attribute(GEN_AI_AGENT_NAME_KEY, "SubBot")
        sub.set_attribute(GEN_AI_AGENT_ID_KEY, "sub-1")
        sub.end()
        main.end()

        spans = self._get_exported_spans()
        sub_exported = spans["invoke_agent SubBot"]
        # main_agent must be MainBot (from parent), not SubBot (own)
        self.assertEqual(sub_exported.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "MainBot")
        self.assertEqual(sub_exported.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "main-1")

    def test_self_promotion_only_for_invoke_agent(self):
        """Non-invoke_agent root spans must NOT self-promote."""
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        chat = self.tracer.start_span("chat gpt-4", context=root_ctx)
        chat.set_attribute(GEN_AI_AGENT_NAME_KEY, "Bot")
        chat.end()

        spans = self._get_exported_spans()
        self.assertIsNone(spans["chat gpt-4"].attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY))


class TestSDKProjectIdPropagation(unittest.TestCase):
    """Verifies Foundry project-id attributes propagate parent → child spans."""

    PROJECT_ID = "/subscriptions/sub/resourceGroups/rg/providers/x/projects/p"

    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(GenAIMainAgentSpanProcessor())
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("test")

    def tearDown(self):
        self.provider.shutdown()

    def _get_exported_spans(self):
        return {s.name: s for s in self.exporter.get_finished_spans()}

    def _stamp_project_id(self, span):
        for key in GEN_AI_PROJECT_ID_KEYS:
            span.set_attribute(key, self.PROJECT_ID)

    def _assert_has_project_id(self, span):
        for key in GEN_AI_PROJECT_ID_KEYS:
            self.assertEqual(span.attributes.get(key), self.PROJECT_ID)

    def test_project_id_propagates_to_child_span(self):
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        self._stamp_project_id(agent_span)

        chat_ctx = trace_api.set_span_in_context(agent_span)
        chat_span = self.tracer.start_span("chat gpt-4", context=chat_ctx)
        chat_span.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self._assert_has_project_id(spans["chat gpt-4"])

    def test_project_id_propagates_through_multiple_levels(self):
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        self._stamp_project_id(agent_span)

        tool_ctx = trace_api.set_span_in_context(agent_span)
        tool_span = self.tracer.start_span("execute_tool get_weather", context=tool_ctx)
        inner_ctx = trace_api.set_span_in_context(tool_span)
        inner_span = self.tracer.start_span("chat gpt-4", context=inner_ctx)
        inner_span.end()
        tool_span.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self._assert_has_project_id(spans["execute_tool get_weather"])
        self._assert_has_project_id(spans["chat gpt-4"])

    def test_project_id_recovered_on_end_when_stamped_after_child(self):
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)

        child_ctx = trace_api.set_span_in_context(agent_span)
        child = self.tracer.start_span("chat gpt-4", context=child_ctx)

        # Stamp project id AFTER the child was created → on_start already fired.
        self._stamp_project_id(agent_span)

        child.end()
        agent_span.end()

        spans = self._get_exported_spans()
        self._assert_has_project_id(spans["chat gpt-4"])

    def test_project_id_propagates_alongside_main_agent_attrs(self):
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")
        agent_span.set_attribute(GEN_AI_AGENT_ID_KEY, "agent-1")
        self._stamp_project_id(agent_span)

        chat_ctx = trace_api.set_span_in_context(agent_span)
        chat_span = self.tracer.start_span("chat gpt-4", context=chat_ctx)
        chat_span.end()
        agent_span.end()

        chat = self._get_exported_spans()["chat gpt-4"]
        self.assertEqual(chat.attributes.get(GEN_AI_MAIN_AGENT_NAME_KEY), "TravelBot")
        self.assertEqual(chat.attributes.get(GEN_AI_MAIN_AGENT_ID_KEY), "agent-1")
        self._assert_has_project_id(chat)

    def test_no_project_id_when_parent_unstamped(self):
        root_ctx = trace_api.set_span_in_context(trace_api.INVALID_SPAN)
        agent_span = self.tracer.start_span("invoke_agent TravelBot", context=root_ctx)
        agent_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        agent_span.set_attribute(GEN_AI_AGENT_NAME_KEY, "TravelBot")

        chat_ctx = trace_api.set_span_in_context(agent_span)
        chat_span = self.tracer.start_span("chat gpt-4", context=chat_ctx)
        chat_span.end()
        agent_span.end()

        chat = self._get_exported_spans()["chat gpt-4"]
        for key in GEN_AI_PROJECT_ID_KEYS:
            self.assertIsNone(chat.attributes.get(key))


if __name__ == "__main__":
    unittest.main()
