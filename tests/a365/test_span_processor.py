# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
# pylint: disable=no-member

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from opentelemetry import baggage, context

from microsoft.opentelemetry.a365.core.exporters.span_processor import (
    A365SpanProcessor,
    COMMON_ATTRIBUTES,
    INVOKE_AGENT_ATTRIBUTES,
)
from microsoft.opentelemetry.a365.core.middleware.baggage_builder import BaggageBuilder
from microsoft.opentelemetry.a365.core.constants import GEN_AI_OPERATION_NAME_KEY

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


class TestA365SpanProcessor(unittest.TestCase):
    # -- identity auto-stamping from constructor --

    def test_stamps_tenant_id_from_constructor(self):
        processor = A365SpanProcessor(tenant_id="cfg-tenant")
        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}
        processor.on_start(span, parent_context=context.get_current())
        span.set_attribute.assert_any_call("microsoft.tenant.id", "cfg-tenant")

    def test_stamps_agent_id_from_constructor(self):
        processor = A365SpanProcessor(agent_id="cfg-agent")
        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}
        processor.on_start(span, parent_context=context.get_current())
        span.set_attribute.assert_any_call("gen_ai.agent.id", "cfg-agent")

    def test_stamps_both_identity_fields(self):
        processor = A365SpanProcessor(tenant_id="t1", agent_id="a1")
        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}
        processor.on_start(span, parent_context=context.get_current())
        span.set_attribute.assert_any_call("microsoft.tenant.id", "t1")
        span.set_attribute.assert_any_call("gen_ai.agent.id", "a1")

    def test_identity_does_not_overwrite_existing(self):
        processor = A365SpanProcessor(tenant_id="cfg-tenant", agent_id="cfg-agent")
        span = MagicMock()
        span.name = "test_span"
        span.attributes = {"microsoft.tenant.id": "existing", "gen_ai.agent.id": "existing"}
        processor.on_start(span, parent_context=context.get_current())
        for call in span.set_attribute.call_args_list:
            self.assertNotIn(call[0][0], ("microsoft.tenant.id", "gen_ai.agent.id"))

    def test_identity_with_empty_baggage(self):
        processor = A365SpanProcessor(tenant_id="t1", agent_id="a1")
        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}
        processor.on_start(span, parent_context=context.get_current())
        self.assertEqual(span.set_attribute.call_count, 2)

    # -- baggage propagation --

    def test_propagates_common_baggage(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}

        ctx = context.get_current()
        ctx = baggage.set_baggage("microsoft.tenant.id", "my-tenant", ctx)
        ctx = baggage.set_baggage("gen_ai.agent.id", "my-agent", ctx)

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_any_call("microsoft.tenant.id", "my-tenant")
        span.set_attribute.assert_any_call("gen_ai.agent.id", "my-agent")

    def test_does_not_overwrite_existing_attributes(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "test_span"
        span.attributes = {"microsoft.tenant.id": "existing-tenant"}

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

    def test_custom_baggage_attribute_propagated_to_genai_span(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Travel_Assistant"
        span.attributes = {"gen_ai.operation.name": "invoke_agent"}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_set_pairs_custom_baggage_is_not_propagated_without_opt_in(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Travel_Assistant"
        span.attributes = {"gen_ai.operation.name": "invoke_agent"}

        with BaggageBuilder().set_pairs({"customer.tier": "gold"}).build():
            processor.on_start(span, parent_context=context.get_current())

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "customer.tier")

    def test_custom_baggage_attribute_does_not_overwrite_span_attribute(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent Travel_Assistant"
        span.attributes = {"gen_ai.operation.name": "invoke_agent", "customer.tier": "direct"}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "customer.tier")

    def test_custom_baggage_attribute_ignored_on_non_genai_span(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "http request"
        span.attributes = {"gen_ai.operation.name": "not_genai"}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "customer.tier")

    def test_custom_baggage_attribute_ignored_for_false_operation_prefixes(self):
        processor = A365SpanProcessor()

        for span_name in ("chatbot_loop", "execute_toolbox"):
            with self.subTest(span_name=span_name):
                span = MagicMock()
                span.name = span_name
                span.attributes = {}

                with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
                    processor.on_start(span, parent_context=context.get_current())

                for call in span.set_attribute.call_args_list:
                    self.assertNotEqual(call[0][0], "customer.tier")

    def test_custom_baggage_attribute_uses_recognized_baggage_operation_name(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "http request"
        span.attributes = {}

        with (
            BaggageBuilder()
            .set_pairs({GEN_AI_OPERATION_NAME_KEY: "chat"})
            .custom_attribute("customer.tier", "gold")
            .build()
        ):
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_attribute_honors_unrecognized_explicit_operation_name(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "chat gpt-4"
        span.attributes = {GEN_AI_OPERATION_NAME_KEY: "not_genai"}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "customer.tier")

    def test_custom_baggage_attribute_propagated_to_text_completion_span(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "TextCompletion summarize"
        span.attributes = {"gen_ai.operation.name": "TextCompletion"}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_attribute_propagated_to_generate_content_span(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "GenerateContent image"
        span.attributes = {"gen_ai.operation.name": "GenerateContent"}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_attribute_propagated_to_known_initial_span_name(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "chat.completions gpt-4o"
        span.attributes = {}

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_attribute_propagated_to_supported_scope_child(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "ChatOpenAI"
        span.attributes = {}
        span.instrumentation_scope = SimpleNamespace(name="microsoft.opentelemetry._genai._langchain")

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_attribute_ignored_for_scope_prefix_without_boundary(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "helper span"
        span.attributes = {}
        span.instrumentation_scope = SimpleNamespace(name="semantic_kernel_helpers")

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "customer.tier")

    # -- explicit but unrecognized operation names --

    def test_custom_baggage_propagated_for_explicit_chain_operation_on_openai_agents_scope(self):
        """OpenAI Agents emits ``chain`` spans this processor does not model."""
        processor = A365SpanProcessor()
        span = _mock_span(
            "chain RunnableSequence",
            {GEN_AI_OPERATION_NAME_KEY: "chain"},
            scope_name=OPENAI_AGENTS_SCOPE,
        )

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_propagated_for_explicit_embeddings_operation_on_agent_framework_scope(self):
        processor = A365SpanProcessor()
        span = _mock_span(
            "embeddings text-embedding-3-small",
            {GEN_AI_OPERATION_NAME_KEY: "embeddings"},
            scope_name=AGENT_FRAMEWORK_SCOPE,
        )

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_propagated_for_explicit_text_completion_operation_on_openai_v2_scope(self):
        processor = A365SpanProcessor()
        span = _mock_span(
            "text_completion gpt-4o",
            {GEN_AI_OPERATION_NAME_KEY: "text_completion"},
            scope_name=OPENAI_V2_SCOPE,
        )

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_propagated_for_other_unrecognized_operations_on_supported_scopes(self):
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

                with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
                    processor.on_start(span, parent_context=context.get_current())

                span.set_attribute.assert_any_call("customer.tier", "gold")

    def test_custom_baggage_ignored_for_unrecognized_explicit_operation_on_unrelated_scope(self):
        processor = A365SpanProcessor()
        span = _mock_span(
            "POST /v1/chain",
            {GEN_AI_OPERATION_NAME_KEY: "chain"},
            scope_name="opentelemetry.instrumentation.requests",
        )

        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            processor.on_start(span, parent_context=context.get_current())

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "customer.tier")

    def test_unrecognized_explicit_operation_with_invoke_agent_span_name_is_not_invoke_agent(self):
        """An unrecognized operation stays unknown, so invoke-only keys are withheld."""
        processor = A365SpanProcessor()
        span = _mock_span(
            "invoke_agent Travel_Assistant",
            {GEN_AI_OPERATION_NAME_KEY: "create_agent"},
            scope_name=OPENAI_AGENTS_SCOPE,
        )

        with (
            BaggageBuilder()
            .set_pairs(
                {
                    "microsoft.a365.caller.agent.id": "caller-1",
                    "server.address": "agent.contoso.com",
                }
            )
            .custom_attribute("customer.tier", "gold")
            .build()
        ):
            processor.on_start(span, parent_context=context.get_current())

        span.set_attribute.assert_any_call("customer.tier", "gold")
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

        ctx = baggage.set_baggage(GEN_AI_OPERATION_NAME_KEY, "invoke_agent", context.get_current())
        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", ctx)

        processor.on_start(span, parent_context=ctx)

        for call in span.set_attribute.call_args_list:
            self.assertNotEqual(call[0][0], "microsoft.a365.caller.agent.id")

    def test_invoke_agent_attributes_use_recognized_baggage_operation_name(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "http request"
        span.attributes = {}

        ctx = context.get_current()
        ctx = baggage.set_baggage(GEN_AI_OPERATION_NAME_KEY, "invoke_agent", ctx)
        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", ctx)

        processor.on_start(span, parent_context=ctx)

        span.set_attribute.assert_any_call("microsoft.a365.caller.agent.id", "caller-1")

    def test_invoke_agent_attributes_ignored_for_raw_prefix_without_boundary(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "invoke_agent.debug"
        span.attributes = {}

        ctx = context.get_current()
        ctx = baggage.set_baggage("microsoft.a365.caller.agent.id", "caller-1", ctx)

        processor.on_start(span, parent_context=ctx)

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

    def test_none_context(self):
        processor = A365SpanProcessor()

        span = MagicMock()
        span.name = "test_span"
        span.attributes = {}

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


if __name__ == "__main__":
    unittest.main()
