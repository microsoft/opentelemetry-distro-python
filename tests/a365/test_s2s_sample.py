# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
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

SAMPLE_DIR = Path(__file__).parents[2] / "samples" / "a365" / "s2s"


def _load_sample_module(module_name, filename):
    spec = importlib.util.spec_from_file_location(f"_a365_s2s_{module_name}", SAMPLE_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_sample_modules():
    module_files = (
        ("sample_config", "sample_config.py"),
        ("token_resolver", "token_resolver.py"),
        ("sample_scenario", "sample_scenario.py"),
        ("s2s_exporter", "s2s_exporter.py"),
    )
    modules = {}
    original_modules: dict[str, ModuleType] = {}
    preexisting_module_names = set(sys.modules).intersection(module_name for module_name, _ in module_files)
    try:
        for module_name, filename in module_files:
            if module_name in preexisting_module_names:
                original_modules[module_name] = sys.modules[module_name]
            module = _load_sample_module(module_name, filename)
            modules[module_name] = module
            sys.modules[module_name] = module
    finally:
        for module_name, _ in module_files:
            if module_name in preexisting_module_names:
                sys.modules[module_name] = original_modules[module_name]
            else:
                sys.modules.pop(module_name, None)
    return tuple(modules[module_name] for module_name, _ in module_files)


sample_config, token_resolver, sample_scenario, s2s_exporter = _load_sample_modules()

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

SAMPLE_CONFIG_ENV = {
    sample_config.A365_SERVICE_CLIENT_ID_ENV: "blueprint-client-id",
    sample_config.A365_SERVICE_CLIENT_SECRET_ENV: "super-secret",
    sample_config.A365_SERVICE_TENANT_ID_ENV: "tenant-123",
    sample_config.A365_AGENT_APP_INSTANCE_ID_ENV: "instance-123",
    sample_config.A365_AGENT_BLUEPRINT_ID_ENV: "blueprint-123",
    sample_config.A365_CALLER_USER_ID_ENV: "user-123",
    sample_config.A365_CALLER_USER_EMAIL_ENV: "user@contoso.com",
    sample_config.A365_CALLER_CLIENT_IP_ENV: "203.0.113.10",
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


def _sample_config():
    return sample_config.SampleConfig(
        client_id="blueprint-client-id",
        client_secret="secret",
        tenant_id="tenant-123",
        agent_instance_id="instance-123",
        agent_blueprint_id="blueprint-123",
        caller_user_id="user-123",
        caller_user_email="user@contoso.com",
        caller_client_ip="203.0.113.10",
    )


@pytest.mark.parametrize("invalid_value", ["", "   ", "<required-value>", "  <required-value>  "])
def test_sample_config_rejects_missing_or_placeholder_values(monkeypatch, invalid_value):
    for name, value in SAMPLE_CONFIG_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(sample_config.A365_AGENT_BLUEPRINT_ID_ENV, invalid_value)

    with pytest.raises(SystemExit, match=sample_config.A365_AGENT_BLUEPRINT_ID_ENV):
        sample_config.SampleConfig.load()


def test_sample_config_hides_secret_from_repr(monkeypatch):
    for name, value in SAMPLE_CONFIG_ENV.items():
        monkeypatch.setenv(name, value)

    config = sample_config.SampleConfig.load()

    assert "super-secret" not in repr(config)


def test_sample_config_creates_deterministic_models(monkeypatch):
    for name, value in SAMPLE_CONFIG_ENV.items():
        monkeypatch.setenv(name, value)

    config = sample_config.SampleConfig.load()

    assert config.create_agent_details() == AgentDetails(
        agent_id="instance-123",
        agent_name="Weather Agent",
        agent_description="Answers weather-related questions",
        agent_blueprint_id="blueprint-123",
        tenant_id="tenant-123",
        provider_name="azure-openai",
        agent_version="1.0.0",
    )
    assert config.create_user_details() == UserDetails(
        user_id="user-123",
        user_email="user@contoso.com",
        user_name="Sample Caller",
        user_client_ip="203.0.113.10",
    )
    assert config.create_request() == Request(
        content="What's the weather in Seattle?",
        session_id="session-s2s-123",
        channel=Channel(name="service", link="https://contoso.example/a365-s2s"),
        conversation_id="conv-s2s-789",
    )


def test_sample_emits_store_required_attributes(captured_spans):
    exporter, provider = captured_spans
    agent, user, request = _sample_inputs()

    result = sample_scenario.emit_sample_telemetry(agent, user, request)
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

    sample_scenario.emit_sample_telemetry(agent, user, request)
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

    resolver = token_resolver.build_s2s_token_resolver(_sample_config())

    assert resolver("agent-123", "different-tenant") is None
    assert "does not match configured tenant" in capsys.readouterr().out
    fake_msal.ConfidentialClientApplication.assert_not_called()


def test_token_resolver_rejects_agent_mismatch(monkeypatch, capsys):
    fake_msal = MagicMock()
    monkeypatch.setitem(sys.modules, "msal", fake_msal)

    resolver = token_resolver.build_s2s_token_resolver(_sample_config())

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

    resolver = token_resolver.build_s2s_token_resolver(_sample_config())

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


def test_main_configures_s2s_export_and_runs_scenario(monkeypatch):
    config = MagicMock()
    agent_details = config.create_agent_details.return_value
    user_details = config.create_user_details.return_value
    request = config.create_request.return_value
    resolver = MagicMock()

    load_config = MagicMock(return_value=config)
    configure_export_logging = MagicMock()
    build_token_resolver = MagicMock(return_value=resolver)
    configure_telemetry = MagicMock()
    emit_telemetry = MagicMock()

    monkeypatch.setattr(s2s_exporter.SampleConfig, "load", load_config)
    monkeypatch.setattr(s2s_exporter, "_configure_export_logging", configure_export_logging)
    monkeypatch.setattr(s2s_exporter, "build_s2s_token_resolver", build_token_resolver)
    monkeypatch.setattr(s2s_exporter, "use_microsoft_opentelemetry", configure_telemetry)
    monkeypatch.setattr(s2s_exporter, "emit_sample_telemetry", emit_telemetry)

    s2s_exporter.main()

    load_config.assert_called_once_with()
    configure_export_logging.assert_called_once_with()
    build_token_resolver.assert_called_once_with(config)
    configure_telemetry.assert_called_once_with(
        enable_a365=True,
        a365_use_s2s_endpoint=True,
        a365_token_resolver=resolver,
    )
    emit_telemetry.assert_called_once_with(agent_details, user_details, request)


def test_sample_modules_do_not_claim_common_module_names():
    sample_modules = (sample_config, token_resolver, sample_scenario, s2s_exporter)

    assert all(module.__name__.startswith("_a365_s2s_") for module in sample_modules)
    assert all(sys.modules.get(module.__name__.removeprefix("_a365_s2s_")) is not module for module in sample_modules)
