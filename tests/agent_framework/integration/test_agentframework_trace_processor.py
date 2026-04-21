# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for Agent Framework trace processor with real Azure OpenAI."""

import logging
import time

import pytest

from microsoft_agents_a365.observability.core.constants import (
    GEN_AI_PROVIDER_NAME_KEY,
    GEN_AI_REQUEST_MODEL_KEY,
    TENANT_ID_KEY,
)

try:
    from agent_framework import RawAgent, tool
    from agent_framework.openai import OpenAIChatClient
    from agent_framework.observability import enable_instrumentation
    from azure.identity import AzureCliCredential
except ImportError:
    pytest.skip(
        "agent_framework library and dependencies required for integration tests",
        allow_module_level=True,
    )

from microsoft.opentelemetry._agent_framework._trace_instrumentor import AgentFrameworkInstrumentor


@tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


class _MockSpanProcessor:
    """Mock span processor that captures spans instead of sending them."""

    def __init__(self):
        self.captured_spans = []

    def on_start(self, span, parent_context=None):
        pass

    def _on_ending(self, span):
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
        from opentelemetry.trace import get_tracer_provider, set_tracer_provider

        current = get_tracer_provider()
        if isinstance(current, TracerProvider):
            current.add_span_processor(self._mock_processor)
        else:
            provider = TracerProvider()
            provider.add_span_processor(self._mock_processor)
            set_tracer_provider(provider)

        enable_instrumentation()
        instrumentor = AgentFrameworkInstrumentor()
        instrumentor.instrument()

        try:
            chat_client = OpenAIChatClient(
                azure_endpoint=azure_openai_config["endpoint"],
                credential=AzureCliCredential(),
                model=azure_openai_config["deployment"],
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
        from opentelemetry.trace import get_tracer_provider, set_tracer_provider

        current = get_tracer_provider()
        if isinstance(current, TracerProvider):
            current.add_span_processor(self._mock_processor)
        else:
            provider = TracerProvider()
            provider.add_span_processor(self._mock_processor)
            set_tracer_provider(provider)

        enable_instrumentation()
        instrumentor = AgentFrameworkInstrumentor()
        instrumentor.instrument()

        try:
            chat_client = OpenAIChatClient(
                azure_endpoint=azure_openai_config["endpoint"],
                credential=AzureCliCredential(),
                model=azure_openai_config["deployment"],
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


if __name__ == "__main__":
    import os
    from os import environ

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    logger.info("=== Starting Agent Framework Integration Test ===")

    # Build config from env vars
    azure_openai_config = {
        "endpoint": environ.get("AZURE_OPENAI_ENDPOINT", ""),
        "deployment": environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", ""),
    }
    agent365_config = {
        "tenant_id": environ.get("A365_TENANT_ID", ""),
        "agent_id": environ.get("A365_AGENT_ID", ""),
    }

    logger.info(f"Azure OpenAI endpoint: {azure_openai_config['endpoint']}")
    logger.info(f"Azure OpenAI deployment: {azure_openai_config['deployment']}")
    logger.info(f"Agent365 tenant: {agent365_config['tenant_id']}")
    logger.info(f"Agent365 agent: {agent365_config['agent_id']}")

    # Set up TracerProvider once — it cannot be overridden after the first call
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import set_tracer_provider

    shared_processor = _MockSpanProcessor()
    provider = TracerProvider()
    provider.add_span_processor(shared_processor)
    set_tracer_provider(provider)

    test_instance = TestAgentFrameworkTraceProcessorIntegration()
    test_instance._mock_processor = shared_processor

    logger.info("--- Running test: trace processor integration ---")
    try:
        test_instance.test_agentframework_trace_processor_integration(azure_openai_config, agent365_config)
        logger.info("PASSED: trace processor integration")
        logger.info(f"  Captured spans: {len(shared_processor.captured_spans)}")
    except Exception as e:
        logger.error(f"FAILED: trace processor integration - {e}", exc_info=True)

    # Clear captured spans for second test, reuse same provider/processor
    shared_processor.captured_spans.clear()

    logger.info("--- Running test: trace processor with tool calls ---")
    try:
        test_instance.test_agentframework_trace_processor_with_tool_calls(azure_openai_config, agent365_config)
        logger.info("PASSED: trace processor with tool calls")
        logger.info(f"  Captured spans: {len(shared_processor.captured_spans)}")
    except Exception as e:
        logger.error(f"FAILED: trace processor with tool calls - {e}", exc_info=True)

    logger.info("=== Done ===")
