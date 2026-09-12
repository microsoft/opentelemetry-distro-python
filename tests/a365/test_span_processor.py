# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
# pylint: disable=no-member

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from opentelemetry import baggage, context
from opentelemetry.sdk.trace import TracerProvider

from microsoft.opentelemetry.a365.constants import (
    APPLY_GUARDRAIL_OPERATION_NAME,
    CHAT_OPERATION_NAME,
    EXECUTE_TOOL_OPERATION_NAME,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
    OUTPUT_MESSAGES_OPERATION_NAME,
)
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_INITIAL_SPAN_NAMES,
    GEN_AI_INSTRUMENTATION_SCOPE_ROOTS,
    GEN_AI_PROCESSOR_OPERATION_NAMES,
    SOURCE_NAME,
)
from microsoft.opentelemetry.a365.core.inference_operation_type import InferenceOperationType
from microsoft.opentelemetry.a365.core.exporters.span_processor import (
    A365SpanProcessor,
    COMMON_ATTRIBUTES,
    INVOKE_AGENT_ATTRIBUTES,
)

LANGCHAIN_SCOPE = "microsoft.opentelemetry._genai._langchain._tracer_instrumentor"
OPENAI_AGENTS_SCOPE = "microsoft.opentelemetry._genai._openai_agents._trace_instrumentor"
UPSTREAM_OPENAI_AGENTS_SCOPE = "opentelemetry.instrumentation.openai_agents"
OPENAI_V2_SCOPE = "opentelemetry.instrumentation.openai_v2"
SEMANTIC_KERNEL_SCOPE = "semantic_kernel.utils.telemetry.model_diagnostics.decorators"
AGENT_FRAMEWORK_SCOPE = "agent_framework"


def _mock_span(name, attributes=None, scope_name=None):
    """Build a mock ReadWriteSpan with a controllable instrumentation scope."""
    span = MagicMock()
    span.name = name
    span.attributes = dict(attributes or {})
    span.instrumentation_scope = SimpleNamespace(name=scope_name, version=None) if scope_name else None
    return span


RECOGNIZED_OPERATION_NAMES = tuple(
    dict.fromkeys(
        [
            INVOKE_AGENT_OPERATION_NAME,
            EXECUTE_TOOL_OPERATION_NAME,
            OUTPUT_MESSAGES_OPERATION_NAME,
            CHAT_OPERATION_NAME,
            APPLY_GUARDRAIL_OPERATION_NAME,
            *(operation.value for operation in InferenceOperationType),
        ]
    )
)


class TestA365SpanProcessor(unittest.TestCase):
    # -- identity auto-stamping from constructor --

    def test_processor_operation_names_include_a365_and_inference_operations(self):
        expected = {
            INVOKE_AGENT_OPERATION_NAME,
            EXECUTE_TOOL_OPERATION_NAME,
            OUTPUT_MESSAGES_OPERATION_NAME,
            CHAT_OPERATION_NAME,
            APPLY_GUARDRAIL_OPERATION_NAME,
            *(operation.value for operation in InferenceOperationType),
        }
        self.assertEqual(GEN_AI_PROCESSOR_OPERATION_NAMES, expected)

    def test_stamps_tenant_id_from_constructor(self):
        processor = A365SpanProcessor(tenant_id="cfg-tenant")
        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME}
        processor.on_start(span, parent_context=context.get_current())
        span.set_attribute.assert_any_call("microsoft.tenant.id", "cfg-tenant")

    def test_stamps_agent_id_from_constructor(self):
        processor = A365SpanProcessor(agent_id="cfg-agent")
        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME}
        processor.on_start(span, parent_context=context.get_current())
        span.set_attribute.assert_any_call("gen_ai.agent.id", "cfg-agent")

    def test_stamps_both_identity_fields(self):
        processor = A365SpanProcessor(tenant_id="t1", agent_id="a1")
        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME}
        processor.on_start(span, parent_context=context.get_current())
        span.set_attribute.assert_any_call("microsoft.tenant.id", "t1")
        span.set_attribute.assert_any_call("gen_ai.agent.id", "a1")

    def test_identity_does_not_overwrite_existing(self):
        processor = A365SpanProcessor(tenant_id="cfg-tenant", agent_id="cfg-agent")
        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {
            GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME,
            "microsoft.tenant.id": "existing",
            "gen_ai.agent.id": "existing",
        }
        processor.on_start(span, parent_context=context.get_current())
        for call in span.set_attribute.call_args_list:
            self.assertNotIn(call[0][0], ("microsoft.tenant.id", "gen_ai.agent.id"))

    def test_identity_with_empty_baggage(self):
        processor = A365SpanProcessor(tenant_id="t1", agent_id="a1")
        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME}
        processor.on_start(span, parent_context=context.get_current())
        self.assertEqual(span.set_attribute.call_count, 2)

    def test_recognized_operation_values_receive_identity_and_common_baggage(self):
        for operation_name in RECOGNIZED_OPERATION_NAMES:
            with self.subTest(operation_name=operation_name):
                processor = A365SpanProcessor(tenant_id="cfg-tenant", agent_id="cfg-agent")
                span = MagicMock()
                span.name = f"{operation_name} Test"
                span.attributes = {GEN_AI_OPERATION_NAME_KEY: operation_name}

                ctx = baggage.set_baggage("user.id", "user-1", context.get_current())

                processor.on_start(span, parent_context=ctx)

                span.set_attribute.assert_any_call("microsoft.tenant.id", "cfg-tenant")
                span.set_attribute.assert_any_call("gen_ai.agent.id", "cfg-agent")
                span.set_attribute.assert_any_call("user.id", "user-1")

    # -- baggage propagation --

    def test_propagates_common_baggage(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME}

        ctx = context.get_current()
        ctx = baggage.set_baggage("microsoft.tenant.id", "my-tenant", ctx)
        ctx = baggage.set_baggage("gen_ai.agent.id", "my-agent", ctx)

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_any_call("microsoft.tenant.id", "my-tenant")
        span.set_attribute.assert_any_call("gen_ai.agent.id", "my-agent")

    def test_does_not_overwrite_existing_attributes(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {
            GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME,
            "microsoft.tenant.id": "existing-tenant",
        }

        ctx = context.get_current()
        ctx = baggage.set_baggage("microsoft.tenant.id", "baggage-tenant", ctx)

        processor.on_start(span, parent_context=ctx)

        # Should not have called set_attribute for tenant since it exists
        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "microsoft.tenant.id")

    def test_invoke_agent_attributes_propagated(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Travel_Assistant"
        span.attributes = {"gen_ai.operation.name": "invoke_agent"}

        ctx = context.get_current()
        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", ctx)
        ctx = baggage.set_baggage("server.address", "example.com", ctx)

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_any_call("microsoft.a365.caller.agent.id", "caller-1")
        span.set_attribute.assert_any_call("server.address", "example.com")

    def test_invoke_agent_attributes_not_propagated_for_other_spans(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "chat gpt-4"
        span.attributes = {"gen_ai.operation.name": "chat"}

        ctx = context.get_current()
        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", ctx)
        ctx = baggage.set_baggage("microsoft.tenant.id", "my-tenant", ctx)

        processor.on_start(span, parent_context=ctx)

        # Tenant should be propagated (common)
        span.set_attribute.assert_any_call("microsoft.tenant.id", "my-tenant")

        # Caller agent should NOT be propagated (invoke-agent only)
        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "microsoft.a365.caller.agent.id")

    def test_empty_baggage(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}

        ctx = context.get_current()

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_not_called()

    def test_unrelated_span_receives_no_identity_or_baggage(self):
        processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
        span = MagicMock()
        span.name = "http.request"
        span.attributes = {}
        ctx = baggage.set_baggage("user.id", "user", context.get_current())
        processor.on_start(span, parent_context=ctx)
        span.set_attribute.assert_not_called()

    def test_recognized_name_prefix_receives_identity_and_common_baggage_without_operation_attribute(self):
        for operation_name in RECOGNIZED_OPERATION_NAMES:
            with self.subTest(operation_name=operation_name):
                processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
                span = MagicMock()
                span.name = f"{operation_name} Test"
                span.attributes = {}
                ctx = baggage.set_baggage("user.id", "user", context.get_current())

                processor.on_start(span, parent_context=ctx)

                span.set_attribute.assert_any_call("microsoft.tenant.id", "tenant")
                span.set_attribute.assert_any_call("gen_ai.agent.id", "agent")
                span.set_attribute.assert_any_call("user.id", "user")

    def test_recognized_baggage_operation_receives_identity_and_common_baggage_without_operation_or_name(self):
        processor = A365SpanProcessor()
        span = MagicMock()
        span.name = "library.span"
        span.attributes = {}

        ctx = context.get_current()
        ctx = baggage.set_baggage(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME, ctx)
        ctx = baggage.set_baggage("microsoft.tenant.id", "tenant", ctx)
        ctx = baggage.set_baggage("gen_ai.agent.id", "agent", ctx)
        ctx = baggage.set_baggage("user.id", "user", ctx)

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_any_call(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
        span.set_attribute.assert_any_call("microsoft.tenant.id", "tenant")
        span.set_attribute.assert_any_call("gen_ai.agent.id", "agent")
        span.set_attribute.assert_any_call("user.id", "user")

    def test_unrecognized_explicit_operation_attribute_does_not_fall_through_to_baggage_or_name(self):
        processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
        span = _mock_span("invoke_agent Test", {GEN_AI_OPERATION_NAME_KEY: "not_gen_ai"})

        ctx = baggage.set_baggage(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME, context.get_current())
        ctx = baggage.set_baggage("user.id", "user", ctx)

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_not_called()

    def test_none_context(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Test"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME}

        # Should not raise
        processor.on_start(span, parent_context=None)

    def test_on_end_does_not_raise(self):
        processor = A365SpanProcessor()
        span = MagicMock()
        processor.on_end(span)

    def test_common_attributes_list(self):
        self.assertIn("microsoft.tenant.id", COMMON_ATTRIBUTES)
        self.assertIn("gen_ai.agent.id", COMMON_ATTRIBUTES)
        self.assertIn("microsoft.session.id", COMMON_ATTRIBUTES)
        self.assertIn("user.id", COMMON_ATTRIBUTES)

    def test_invoke_agent_attributes_list(self):
        self.assertIn("microsoft.a365.caller.agent.id", INVOKE_AGENT_ATTRIBUTES)
        self.assertIn("server.address", INVOKE_AGENT_ATTRIBUTES)
        self.assertIn("server.port", INVOKE_AGENT_ATTRIBUTES)


class TestA365SpanProcessorGenAiInstrumentationSignals(unittest.TestCase):
    """Spans that only become identifiable as GenAI *after* ``on_start``.

    LangChain and Semantic Kernel set ``gen_ai.operation.name`` (and rename the
    span) once the call completes, so ``on_start`` sees only the raw span name.
    The instrumentation scope is the signal that is already available.
    """

    def _baggage_context(self):
        ctx = baggage.set_baggage("microsoft.tenant.id", "baggage-tenant", context.get_current())
        ctx = baggage.set_baggage("gen_ai.agent.id", "baggage-agent", ctx)
        ctx = baggage.set_baggage("microsoft.session.id", "session-1", ctx)
        ctx = baggage.set_baggage("user.id", "user-1", ctx)
        return ctx

    def _assert_enriched(self, span):
        span.set_attribute.assert_any_call("microsoft.tenant.id", "baggage-tenant")
        span.set_attribute.assert_any_call("gen_ai.agent.id", "baggage-agent")
        span.set_attribute.assert_any_call("microsoft.session.id", "session-1")
        span.set_attribute.assert_any_call("user.id", "user-1")

    # -- scope constants --

    def test_scope_roots_cover_supported_gen_ai_instrumentations(self):
        self.assertIn(SOURCE_NAME, GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)
        self.assertIn("semantic_kernel", GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)
        self.assertIn("agent_framework", GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)
        self.assertIn("microsoft.opentelemetry._genai", GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)
        self.assertIn("opentelemetry.instrumentation.openai_v2", GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)
        self.assertIn("opentelemetry.instrumentation.openai_agents", GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)

    def test_initial_span_names_cover_semantic_kernel_completions(self):
        self.assertIn("chat.completions", GEN_AI_INITIAL_SPAN_NAMES)
        self.assertIn("chat.streaming_completions", GEN_AI_INITIAL_SPAN_NAMES)
        self.assertIn("text.completions", GEN_AI_INITIAL_SPAN_NAMES)
        self.assertIn("text_completions", GEN_AI_INITIAL_SPAN_NAMES)

    # -- positive cases --

    def test_langchain_chat_model_span_is_enriched(self):
        """The initial LangChain chat-model span is named after the model class."""
        processor = A365SpanProcessor()
        span = _mock_span("ChatOpenAI", scope_name=LANGCHAIN_SCOPE)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_langchain_chain_span_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span("RunnableSequence", scope_name=LANGCHAIN_SCOPE)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_openai_agents_workflow_span_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span("Agent workflow", scope_name=OPENAI_AGENTS_SCOPE)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_semantic_kernel_chat_completions_span_is_enriched(self):
        """Semantic Kernel starts chat spans as ``chat.completions <model>``."""
        processor = A365SpanProcessor()
        span = _mock_span("chat.completions gpt-4o", scope_name=SEMANTIC_KERNEL_SCOPE)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_semantic_kernel_chat_completions_span_enriched_without_scope(self):
        """The known initial span name alone is enough, independent of scope."""
        processor = A365SpanProcessor()
        span = _mock_span("chat.completions gpt-4o")

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_semantic_kernel_streaming_completions_span_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span("chat.streaming_completions gpt-4o", scope_name=SEMANTIC_KERNEL_SCOPE)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_semantic_kernel_auto_function_invocation_span_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span("AutoFunctionInvocationLoop", scope_name="semantic_kernel.connectors.ai")

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_agent_framework_scope_root_matches_exactly(self):
        processor = A365SpanProcessor()
        span = _mock_span("embeddings text-embedding-3-small", scope_name=AGENT_FRAMEWORK_SCOPE)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_a365_source_name_scope_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span("custom-a365-span", scope_name=SOURCE_NAME)

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_scope_signal_does_not_mark_span_as_invoke_agent(self):
        """Scope-only recognition must not leak invoke_agent-only attributes."""
        processor = A365SpanProcessor()
        span = _mock_span("ChatOpenAI", scope_name=LANGCHAIN_SCOPE)

        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", self._baggage_context())

        processor.on_start(span, parent_context=ctx)

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "microsoft.a365.caller.agent.id")

    # -- explicit but unrecognized operation names --

    def test_openai_agents_scope_with_explicit_chain_operation_is_enriched(self):
        """OpenAI Agents emits ``chain`` spans this processor does not model."""
        processor = A365SpanProcessor()
        span = _mock_span(
            "chain RunnableSequence",
            {GEN_AI_OPERATION_NAME_KEY: "chain"},
            scope_name=OPENAI_AGENTS_SCOPE,
        )

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_agent_framework_scope_with_explicit_embeddings_operation_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span(
            "embeddings text-embedding-3-small",
            {GEN_AI_OPERATION_NAME_KEY: "embeddings"},
            scope_name=AGENT_FRAMEWORK_SCOPE,
        )

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_openai_v2_scope_with_explicit_text_completion_operation_is_enriched(self):
        processor = A365SpanProcessor()
        span = _mock_span(
            "text_completion gpt-4o",
            {GEN_AI_OPERATION_NAME_KEY: "text_completion"},
            scope_name=OPENAI_V2_SCOPE,
        )

        processor.on_start(span, parent_context=self._baggage_context())

        self._assert_enriched(span)

    def test_supported_scopes_with_other_unrecognized_operations_are_enriched(self):
        for scope_name, operation_name in (
            (UPSTREAM_OPENAI_AGENTS_SCOPE, "create_agent"),
            (LANGCHAIN_SCOPE, "generate_content"),
            (SEMANTIC_KERNEL_SCOPE, "embeddings"),
        ):
            with self.subTest(scope_name=scope_name, operation_name=operation_name):
                processor = A365SpanProcessor()
                span = _mock_span(
                    f"{operation_name} target",
                    {GEN_AI_OPERATION_NAME_KEY: operation_name},
                    scope_name=scope_name,
                )

                processor.on_start(span, parent_context=self._baggage_context())

                self._assert_enriched(span)

    def test_unrecognized_explicit_operation_on_unrelated_scope_is_untouched(self):
        processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
        span = _mock_span(
            "POST /v1/chain",
            {GEN_AI_OPERATION_NAME_KEY: "chain"},
            scope_name="opentelemetry.instrumentation.requests",
        )

        processor.on_start(span, parent_context=self._baggage_context())

        span.set_attribute.assert_not_called()

    def test_unrecognized_explicit_operation_with_invoke_agent_span_name_is_not_invoke_agent(self):
        """An unrecognized operation stays unknown, so invoke-only keys are withheld."""
        processor = A365SpanProcessor()
        span = _mock_span(
            "invoke_agent Travel_Assistant",
            {GEN_AI_OPERATION_NAME_KEY: "create_agent"},
            scope_name=OPENAI_AGENTS_SCOPE,
        )

        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", self._baggage_context())
        ctx = baggage.set_baggage("server.address", "agent.contoso.com", ctx)

        processor.on_start(span, parent_context=ctx)

        self._assert_enriched(span)
        for call in span.set_attribute.call_args_list:
            self.assertNotIn(call[0][0], ("microsoft.a365.caller.agent.id", "server.address"))

    def test_unrecognized_explicit_operation_ignores_invoke_agent_baggage_operation(self):
        """Baggage inference is skipped once an explicit operation is present."""
        processor = A365SpanProcessor()
        span = _mock_span(
            "chain RunnableSequence",
            {GEN_AI_OPERATION_NAME_KEY: "chain"},
            scope_name=LANGCHAIN_SCOPE,
        )

        ctx = baggage.set_baggage(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME, self._baggage_context())
        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", ctx)

        processor.on_start(span, parent_context=ctx)

        self._assert_enriched(span)
        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "microsoft.a365.caller.agent.id")

    # -- negative cases --

    def test_unrelated_scope_with_nearby_span_name_is_untouched(self):
        for span_name in ("chat.completions.retry", "chatty service", "text_completionsX", "invoke_agentic"):
            with self.subTest(span_name=span_name):
                processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
                span = _mock_span(span_name, scope_name="opentelemetry.instrumentation.requests")

                processor.on_start(span, parent_context=self._baggage_context())

                span.set_attribute.assert_not_called()

    def test_nearby_scope_names_are_untouched(self):
        for scope_name in (
            "semantic_kernel_helpers",
            "agent_framework_extras",
            "my.semantic_kernel",
            "microsoft.opentelemetry._genai_extras",
            "opentelemetry.instrumentation.openai_v2_extras",
            "Agent365SdkExtras",
        ):
            with self.subTest(scope_name=scope_name):
                processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
                span = _mock_span("SomeOperation", scope_name=scope_name)

                processor.on_start(span, parent_context=self._baggage_context())

                span.set_attribute.assert_not_called()

    def test_common_http_span_is_untouched(self):
        processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
        span = _mock_span("GET /api/orders", scope_name="opentelemetry.instrumentation.requests")

        processor.on_start(span, parent_context=self._baggage_context())

        span.set_attribute.assert_not_called()

    def test_missing_instrumentation_scope_is_tolerated(self):
        processor = A365SpanProcessor(tenant_id="tenant", agent_id="agent")
        span = _mock_span("GET /api/orders")
        del span.instrumentation_scope

        processor.on_start(span, parent_context=self._baggage_context())

        span.set_attribute.assert_not_called()


class TestA365SpanProcessorWithTracerProvider(unittest.TestCase):
    """End-to-end checks against a real SDK ``TracerProvider``.

    Mirrors the distro's registration order: ``A365SpanProcessor`` is attached
    when the provider is built, platform processors are attached later by the
    instrumentors. ``A365SpanProcessor.on_start`` therefore runs *before* the
    Semantic Kernel processor renames the span and sets its operation name.
    """

    def setUp(self):
        self.provider = TracerProvider()
        self.provider.add_span_processor(A365SpanProcessor())

        from microsoft.opentelemetry._semantic_kernel._span_processor import SemanticKernelSpanProcessor

        self.provider.add_span_processor(SemanticKernelSpanProcessor())

        ctx = baggage.set_baggage("microsoft.tenant.id", "tenant-1", context.get_current())
        ctx = baggage.set_baggage("gen_ai.agent.id", "agent-1", ctx)
        ctx = baggage.set_baggage("microsoft.session.id", "session-1", ctx)
        ctx = baggage.set_baggage("user.id", "user-1", ctx)
        self._token = context.attach(ctx)

    def tearDown(self):
        context.detach(self._token)
        self.provider.shutdown()

    def _start_span(self, scope_name, span_name):
        tracer = self.provider.get_tracer(scope_name)
        span = tracer.start_span(span_name)
        span.end()
        return span

    def test_langchain_chat_model_span_keeps_identity(self):
        span = self._start_span(LANGCHAIN_SCOPE, "ChatOpenAI")

        self.assertEqual(span.attributes.get("microsoft.tenant.id"), "tenant-1")
        self.assertEqual(span.attributes.get("gen_ai.agent.id"), "agent-1")
        self.assertEqual(span.attributes.get("microsoft.session.id"), "session-1")
        self.assertEqual(span.attributes.get("user.id"), "user-1")

    def test_semantic_kernel_chat_completions_span_keeps_identity(self):
        span = self._start_span(SEMANTIC_KERNEL_SCOPE, "chat.completions gpt-4o")

        # The Semantic Kernel processor runs after A365 and renames the span.
        self.assertEqual(span.name, "chat gpt-4o")
        self.assertEqual(span.attributes.get("gen_ai.operation.name"), "chat")
        self.assertEqual(span.attributes.get("microsoft.tenant.id"), "tenant-1")
        self.assertEqual(span.attributes.get("gen_ai.agent.id"), "agent-1")
        self.assertEqual(span.attributes.get("user.id"), "user-1")

    def test_invoke_agent_span_keeps_identity(self):
        span = self._start_span(LANGCHAIN_SCOPE, "invoke_agent Travel_Assistant")

        self.assertEqual(span.attributes.get("microsoft.tenant.id"), "tenant-1")
        self.assertEqual(span.attributes.get("gen_ai.agent.id"), "agent-1")

    def test_unrelated_http_span_is_untouched(self):
        span = self._start_span("opentelemetry.instrumentation.requests", "GET")

        self.assertIsNone((span.attributes or {}).get("microsoft.tenant.id"))
        self.assertIsNone((span.attributes or {}).get("gen_ai.agent.id"))
        self.assertIsNone((span.attributes or {}).get("user.id"))


if __name__ == "__main__":
    unittest.main()
