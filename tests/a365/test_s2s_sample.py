# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from microsoft.opentelemetry.a365.core import (
    AgentDetails,
    ApplyGuardrailScope,
    Channel,
    ExecuteToolScope,
    InferenceScope,
    InvokeAgentScope,
    OutputScope,
    Request,
    UserDetails,
)
from microsoft.opentelemetry.a365.core.constants import SOURCE_NAME
from microsoft.opentelemetry.a365.core.exporters.enriching_span_processor import (
    _EnrichingBatchSpanProcessor,
)
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope

SAMPLE_PATH = Path(__file__).parents[2] / "samples" / "a365" / "s2s" / "s2s_exporter.py"
SPEC = importlib.util.spec_from_file_location("a365_s2s_exporter_sample", SAMPLE_PATH)
assert SPEC is not None and SPEC.loader is not None
s2s_exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s2s_exporter)

COMMON_REQUIRED = {
    "microsoft.a365.agent.blueprint.id",
    "gen_ai.agent.id",
    "gen_ai.agent.name",
    "client.address",
    "user.id",
    "user.email",
    "microsoft.channel.name",
    "gen_ai.conversation.id",
    "gen_ai.operation.name",
    "microsoft.tenant.id",
}
INVOKE_REQUIRED = COMMON_REQUIRED | {
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "server.address",
    "server.port",
}
INFERENCE_REQUIRED = COMMON_REQUIRED | {
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.provider.name",
    "gen_ai.request.model",
}
TOOL_REQUIRED = COMMON_REQUIRED | {
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.id",
    "gen_ai.tool.call.result",
    "gen_ai.tool.name",
    "gen_ai.tool.type",
}
OUTPUT_REQUIRED = COMMON_REQUIRED | {"gen_ai.output.messages"}
GUARDRAIL_REQUIRED = COMMON_REQUIRED

S2S_ENV = {
    s2s_exporter.A365_SERVICE_CLIENT_ID_ENV: "blueprint-client-id",
    s2s_exporter.A365_SERVICE_CLIENT_SECRET_ENV: "secret",
    s2s_exporter.A365_SERVICE_TENANT_ID_ENV: "tenant-123",
    s2s_exporter.A365_AGENT_APP_INSTANCE_ID_ENV: "instance-123",
}


@pytest.fixture(name="captured_spans")
def _captured_spans(monkeypatch):
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    processor = _EnrichingBatchSpanProcessor(
        exporter,
        max_queue_size=64,
        schedule_delay_millis=60_000,
        max_export_batch_size=64,
    )
    provider.add_span_processor(processor)
    tracer = provider.get_tracer(SOURCE_NAME)
    scope_types = (
        OpenTelemetryScope,
        ApplyGuardrailScope,
        ExecuteToolScope,
        InferenceScope,
        InvokeAgentScope,
        OutputScope,
    )
    for scope_type in scope_types:
        scope_type._tracer = tracer

    yield exporter, provider

    provider.shutdown()
    for scope_type in scope_types:
        scope_type._tracer = None


def _sample_inputs():
    agent = AgentDetails(
        agent_id="agent-123",
        agent_name="Weather Agent",
        agent_description="Answers weather questions",
        agent_blueprint_id="blueprint-123",
        tenant_id="tenant-123",
        provider_name="azure-openai",
        agent_version="1.0.0",
    )
    user = UserDetails(
        user_id="user-123",
        user_email="user@contoso.com",
        user_name="Sample User",
        user_client_ip="203.0.113.10",
    )
    request = Request(
        content="What's the weather in Seattle?",
        session_id="session-123",
        channel=Channel(name="service", link="https://contoso.example/channel"),
        conversation_id="conversation-123",
    )
    return agent, user, request


def test_sample_emits_store_required_attributes(captured_spans):
    exporter, provider = captured_spans
    agent, user, request = _sample_inputs()

    result = s2s_exporter._emit_sample_telemetry(agent, user, request)
    assert result == "It's currently 62°F and partly cloudy in Seattle."
    assert provider.force_flush()

    spans = exporter.get_finished_spans()
    by_operation = {
        span.attributes["gen_ai.operation.name"]: span for span in spans if "gen_ai.operation.name" in span.attributes
    }
    assert {
        "invoke_agent",
        "apply_guardrail",
        "Chat",
        "execute_tool",
        "output_messages",
    }.issubset(by_operation)

    required_by_operation = {
        "invoke_agent": INVOKE_REQUIRED,
        "apply_guardrail": GUARDRAIL_REQUIRED,
        "Chat": INFERENCE_REQUIRED,
        "execute_tool": TOOL_REQUIRED,
        "output_messages": OUTPUT_REQUIRED,
    }
    for operation, required in required_by_operation.items():
        attributes = dict(by_operation[operation].attributes)
        assert required <= attributes.keys(), f"{operation} missing {required - attributes.keys()}"
        assert "microsoft.agent.user.id" not in attributes
        assert "microsoft.agent.user.email" not in attributes


def test_sample_emits_guardrail_details_and_finding(captured_spans):
    exporter, provider = captured_spans
    agent, user, request = _sample_inputs()

    s2s_exporter._emit_sample_telemetry(agent, user, request)
    assert provider.force_flush()

    guardrail = next(
        span
        for span in exporter.get_finished_spans()
        if span.attributes.get("gen_ai.operation.name") == "apply_guardrail"
    )
    assert guardrail.attributes["microsoft.security.target.type"] == "llm_input"
    assert guardrail.attributes["microsoft.security.decision.type"] == "allow"
    assert guardrail.attributes["microsoft.guardian.name"] == "Sample Content Safety"
    assert [event.name for event in guardrail.events] == ["microsoft.security.finding"]


def test_token_resolver_rejects_tenant_mismatch(monkeypatch, capsys):
    fake_msal = MagicMock()
    monkeypatch.setitem(sys.modules, "msal", fake_msal)
    for name, value in S2S_ENV.items():
        monkeypatch.setenv(name, value)

    resolver = s2s_exporter.build_s2s_token_resolver()

    assert resolver("agent-123", "different-tenant") is None
    assert "does not match configured tenant" in capsys.readouterr().out
    fake_msal.ConfidentialClientApplication.assert_not_called()


def test_token_resolver_rejects_agent_mismatch(monkeypatch, capsys):
    fake_msal = MagicMock()
    monkeypatch.setitem(sys.modules, "msal", fake_msal)
    for name, value in S2S_ENV.items():
        monkeypatch.setenv(name, value)

    resolver = s2s_exporter.build_s2s_token_resolver()

    assert resolver("different-agent", "tenant-123") is None
    assert "does not match configured agent instance" in capsys.readouterr().out
    fake_msal.ConfidentialClientApplication.assert_not_called()


def test_token_resolver_caches_by_tenant_and_agent(monkeypatch):
    first_app = MagicMock()
    first_app.acquire_token_for_client.return_value = {"access_token": "agent-token"}
    second_app = MagicMock()
    second_app.acquire_token_for_client.return_value = {
        "access_token": "observability-token",
        "expires_in": 3600,
    }
    fake_msal = MagicMock()
    fake_msal.ConfidentialClientApplication.side_effect = [first_app, second_app]
    monkeypatch.setitem(sys.modules, "msal", fake_msal)
    for name, value in S2S_ENV.items():
        monkeypatch.setenv(name, value)

    resolver = s2s_exporter.build_s2s_token_resolver()

    assert resolver("instance-123", "tenant-123") == "observability-token"
    assert resolver("instance-123", "tenant-123") == "observability-token"
    assert fake_msal.ConfidentialClientApplication.call_count == 2


def test_configure_export_logging_adds_one_named_handler():
    logger = logging.getLogger("microsoft.opentelemetry.a365.core.exporters.agent365_exporter")
    original_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    try:
        logger.handlers = []
        s2s_exporter._configure_export_logging()
        s2s_exporter._configure_export_logging()

        matching = [handler for handler in logger.handlers if handler.name == "a365-s2s-sample-export-logging"]
        assert len(matching) == 1
        assert logger.propagate is False
    finally:
        logger.handlers = original_handlers
        logger.propagate = original_propagate
