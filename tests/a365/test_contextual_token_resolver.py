# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from microsoft.opentelemetry.a365.core.exporters.agent365_exporter import (
    _Agent365Exporter,
)
from microsoft.opentelemetry.a365.core.exporters.token_resolver_context import (
    AgentIdentity,
    TokenResolverContext,
)


def _make_span(
    tenant_id="t1",
    agent_id="a1",
    agentic_user_id=None,
    name="test_span",
    trace_id=0x1234,
    span_id=0x5678,
    operation_name="invoke_agent",
):
    span = MagicMock()
    span.name = name
    attrs = {
        "microsoft.tenant.id": tenant_id,
        "gen_ai.agent.id": agent_id,
    }
    if operation_name is not None:
        attrs["gen_ai.operation.name"] = operation_name
    if agentic_user_id is not None:
        attrs["microsoft.agent.user.id"] = agentic_user_id
    span.attributes = attrs

    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.span_id = span_id
    span.context = ctx
    span.get_span_context.return_value = ctx

    span.parent = None
    span.kind = SpanKind.INTERNAL
    span.start_time = 1000000000
    span.end_time = 2000000000

    status = MagicMock()
    status.status_code = StatusCode.OK
    status.description = ""
    span.status = status

    span.events = []
    span.links = []

    scope = MagicMock()
    scope.name = "test_scope"
    scope.version = "1.0"
    span.instrumentation_scope = scope

    resource = MagicMock()
    resource.attributes = {"service.name": "test-service"}
    span.resource = resource

    return span


class TestAgentIdentity(unittest.TestCase):
    def test_creates_with_agent_id_only(self):
        identity = AgentIdentity("agent-123")
        self.assertEqual(identity.agent_id, "agent-123")
        self.assertIsNone(identity.agentic_user_id)

    def test_creates_with_both_ids(self):
        identity = AgentIdentity("agent-123", "user-456")
        self.assertEqual(identity.agent_id, "agent-123")
        self.assertEqual(identity.agentic_user_id, "user-456")

    def test_raises_on_empty_agent_id(self):
        with self.assertRaises(ValueError):
            AgentIdentity("")

    def test_raises_on_none_agent_id(self):
        with self.assertRaises(ValueError):
            AgentIdentity(None)


class TestTokenResolverContext(unittest.TestCase):
    def test_creates_with_identity_and_tenant(self):
        identity = AgentIdentity("agent-1", "user-1")
        context = TokenResolverContext(identity, "tenant-1")
        self.assertEqual(context.identity.agent_id, "agent-1")
        self.assertEqual(context.identity.agentic_user_id, "user-1")
        self.assertEqual(context.tenant_id, "tenant-1")

    def test_raises_on_none_identity(self):
        with self.assertRaises(ValueError):
            TokenResolverContext(None, "tenant-1")

    def test_raises_on_empty_tenant_id(self):
        identity = AgentIdentity("agent-1")
        with self.assertRaises(ValueError):
            TokenResolverContext(identity, "")


class TestContextualTokenResolverInit(unittest.TestCase):
    def test_raises_when_neither_resolver_provided(self):
        with self.assertRaises(ValueError):
            _Agent365Exporter(token_resolver=None, contextual_token_resolver=None)

    def test_creates_with_contextual_resolver_only(self):
        exporter = _Agent365Exporter(contextual_token_resolver=lambda ctx: "token")
        self.assertIsNotNone(exporter)
        exporter.shutdown()

    def test_creates_with_token_resolver_only(self):
        exporter = _Agent365Exporter(token_resolver=lambda a, t: "token")
        self.assertIsNotNone(exporter)
        exporter.shutdown()

    def test_creates_with_both_resolvers(self):
        exporter = _Agent365Exporter(
            token_resolver=lambda a, t: "token1",
            contextual_token_resolver=lambda ctx: "token2",
        )
        self.assertIsNotNone(exporter)
        exporter.shutdown()


class TestContextualTokenResolverExport(unittest.TestCase):
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter._Agent365Exporter._post_with_retries")
    @patch.dict(os.environ, {}, clear=True)
    def test_contextual_resolver_called_with_context(self, mock_post):
        mock_post.return_value = True
        resolver = MagicMock(return_value="ctx-token")
        exporter = _Agent365Exporter(contextual_token_resolver=resolver)
        span = _make_span(tenant_id="t1", agent_id="a1", agentic_user_id="user-42")
        exporter.export([span])

        resolver.assert_called_once()
        ctx = resolver.call_args[0][0]
        self.assertIsInstance(ctx, TokenResolverContext)
        self.assertEqual(ctx.identity.agent_id, "a1")
        self.assertEqual(ctx.identity.agentic_user_id, "user-42")
        self.assertEqual(ctx.tenant_id, "t1")
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter._Agent365Exporter._post_with_retries")
    @patch.dict(os.environ, {}, clear=True)
    def test_contextual_resolver_null_agentic_user_id(self, mock_post):
        mock_post.return_value = True
        resolver = MagicMock(return_value="ctx-token")
        exporter = _Agent365Exporter(contextual_token_resolver=resolver)
        span = _make_span(tenant_id="t1", agent_id="a1")  # no agentic_user_id
        exporter.export([span])

        ctx = resolver.call_args[0][0]
        self.assertIsNone(ctx.identity.agentic_user_id)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter._Agent365Exporter._post_with_retries")
    @patch.dict(os.environ, {}, clear=True)
    def test_contextual_resolver_takes_precedence_over_token_resolver(self, mock_post):
        mock_post.return_value = True
        token_resolver = MagicMock(return_value="old-token")
        contextual_resolver = MagicMock(return_value="new-token")
        exporter = _Agent365Exporter(
            token_resolver=token_resolver,
            contextual_token_resolver=contextual_resolver,
        )
        span = _make_span(tenant_id="t1", agent_id="a1")
        exporter.export([span])

        # contextual_resolver should be called; token_resolver should NOT
        contextual_resolver.assert_called_once()
        token_resolver.assert_not_called()
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter._Agent365Exporter._post_with_retries")
    @patch.dict(os.environ, {}, clear=True)
    def test_token_resolver_used_when_no_contextual(self, mock_post):
        mock_post.return_value = True
        token_resolver = MagicMock(return_value="old-token")
        exporter = _Agent365Exporter(token_resolver=token_resolver)
        span = _make_span(tenant_id="t1", agent_id="a1")
        exporter.export([span])

        token_resolver.assert_called_once_with("a1", "t1")
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter._Agent365Exporter._post_with_retries")
    @patch.dict(os.environ, {}, clear=True)
    def test_contextual_resolver_exception_marks_failure(self, mock_post):
        mock_post.return_value = True
        resolver = MagicMock(side_effect=Exception("auth error"))
        exporter = _Agent365Exporter(contextual_token_resolver=resolver)
        span = _make_span(tenant_id="t1", agent_id="a1")
        result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.FAILURE)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter._Agent365Exporter._post_with_retries")
    @patch.dict(os.environ, {}, clear=True)
    def test_contextual_resolver_returns_none_no_auth_header(self, mock_post):
        mock_post.return_value = True
        resolver = MagicMock(return_value=None)
        exporter = _Agent365Exporter(contextual_token_resolver=resolver)
        span = _make_span(tenant_id="t1", agent_id="a1")
        result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter.shutdown()


class TestExporterOptionsContextualResolver(unittest.TestCase):
    def test_options_accepts_contextual_resolver(self):
        from microsoft.opentelemetry.a365.core.exporters.agent365_exporter_options import (
            Agent365ExporterOptions,
        )

        resolver = lambda ctx: "token"
        opts = Agent365ExporterOptions(contextual_token_resolver=resolver)
        self.assertIs(opts.contextual_token_resolver, resolver)
        self.assertIsNone(opts.token_resolver)

    def test_options_accepts_both_resolvers(self):
        from microsoft.opentelemetry.a365.core.exporters.agent365_exporter_options import (
            Agent365ExporterOptions,
        )

        tr = lambda a, t: "token1"
        cr = lambda ctx: "token2"
        opts = Agent365ExporterOptions(token_resolver=tr, contextual_token_resolver=cr)
        self.assertIs(opts.token_resolver, tr)
        self.assertIs(opts.contextual_token_resolver, cr)


if __name__ == "__main__":
    unittest.main()
