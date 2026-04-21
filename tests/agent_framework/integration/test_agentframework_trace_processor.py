# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for Agent Framework trace processor with real Azure OpenAI."""

import time

import pytest

from microsoft_agents_a365.observability.core.constants import (
    GEN_AI_PROVIDER_NAME_KEY,
    GEN_AI_REQUEST_MODEL_KEY,
    TENANT_ID_KEY,
)

try:
    from agent_framework import RawAgent, ai_function
    from agent_framework.azure import AzureOpenAIChatClient
    from agent_framework.observability import setup_observability
    from azure.identity import AzureCliCredential
except ImportError:
    pytest.skip(
        "agent_framework library and dependencies required for integration tests",
        allow_module_level=True,
    )

from microsoft.opentelemetry._agent_framework._trace_instrumentor import AgentFrameworkInstrumentor


@ai_function
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


class _MockSpanProcessor:
    """Mock span processor that captures spans instead of sending them."""

    def __init__(self):
        self.captured_spans = []

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        self.captured_spans.append(span)

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


@pytest.mark.integration
class TestAgentFrameworkTraceProcessorIntegration:
    """Integration tests for AgentFramework trace processor with real Azure OpenAI."""

    def setup_method(self):
        self._mock_processor = _MockSpanProcessor()

    def test_agentframework_trace_processor_integration(self, azure_openai_config, agent365_config):
        """Test AgentFramework trace processor with real Azure OpenAI call."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.trace import set_tracer_provider

        provider = TracerProvider()
        provider.add_span_processor(self._mock_processor)
        set_tracer_provider(provider)

        setup_observability()
        instrumentor = AgentFrameworkInstrumentor()
        instrumentor.instrument()

        try:
            chat_client = AzureOpenAIChatClient(
                endpoint=azure_openai_config["endpoint"],
                credential=AzureCliCredential(),
                deployment_name=azure_openai_config["deployment"],
                api_version=azure_openai_config["api_version"],
            )
            agent = RawAgent(
                client=chat_client,
                instructions="You are a helpful assistant.",
                tools=[],
            )

            import asyncio

            async def run_agent():
                return await agent.run("What can you do with agent framework?")

            response = asyncio.run(run_agent())
            time.sleep(1)

            assert len(self._mock_processor.captured_spans) > 0
            assert response is not None
            assert len(response.text) > 0

        finally:
            instrumentor.uninstrument()

    def test_agentframework_trace_processor_with_tool_calls(self, azure_openai_config, agent365_config):
        """Test AgentFramework trace processor with tool calls."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.trace import set_tracer_provider

        provider = TracerProvider()
        provider.add_span_processor(self._mock_processor)
        set_tracer_provider(provider)

        setup_observability()
        instrumentor = AgentFrameworkInstrumentor()
        instrumentor.instrument()

        try:
            chat_client = AzureOpenAIChatClient(
                endpoint=azure_openai_config["endpoint"],
                credential=AzureCliCredential(),
                deployment_name=azure_openai_config["deployment"],
                api_version=azure_openai_config["api_version"],
            )
            agent = RawAgent(
                client=chat_client,
                instructions="You are a helpful agent framework assistant.",
                tools=[add_numbers],
            )

            import asyncio

            async def run_agent_with_tool():
                return await agent.run("What is 15 + 27?")

            response = asyncio.run(run_agent_with_tool())
            time.sleep(1)

            assert len(self._mock_processor.captured_spans) > 0
            assert response is not None
            assert len(response.text) > 0
            assert "42" in response.text

        finally:
            instrumentor.uninstrument()
