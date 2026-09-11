# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
# pylint: disable=no-member

import unittest
from unittest.mock import MagicMock

from opentelemetry import baggage, context

from microsoft.opentelemetry.a365.core.exporters.span_processor import (
    A365SpanProcessor,
    COMMON_ATTRIBUTES,
    INVOKE_AGENT_ATTRIBUTES,
)
from microsoft.opentelemetry.a365.core.middleware.baggage_builder import BaggageBuilder


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
