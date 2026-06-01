# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for LangChain message format mapping.

These tests use the real A365 observability pipeline configured by the distro
(``use_microsoft_opentelemetry``).  The shared ``distro_exporter`` fixture
(session-scoped, from conftest) adds a ``SpanCapturingExporter`` behind
``_EnrichingBatchSpanProcessor`` so spans arrive here after enrichment —
matching the real A365 export path without sending data to a real endpoint.

Currently LangChain emits gen_ai.input.messages / gen_ai.output.messages
as plain JSON string arrays (e.g. '["Hello"]'). These tests document that
raw format and will verify the A365 structured array format once the mapper is added.
"""

import json
import time
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan

try:
    from langchain_openai import AzureChatOpenAI
except ImportError:
    pytest.skip(
        "langchain-openai required for LangChain integration tests",
        allow_module_level=True,
    )

from opentelemetry.trace import get_tracer_provider

from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
)

from ..conftest import SpanCapturingExporter


@pytest.mark.integration
class TestLangChainMessageFormat:
    """Capture real LangChain span attributes and verify message structure."""

    @pytest.fixture
    def llm(self, azure_openai_config: dict[str, Any]) -> AzureChatOpenAI:
        """Create a real Azure OpenAI LangChain chat model."""
        return AzureChatOpenAI(
            azure_endpoint=azure_openai_config["endpoint"],
            api_key=azure_openai_config["api_key"],
            azure_deployment=azure_openai_config["deployment"],
            api_version=azure_openai_config["api_version"],
        )

    @staticmethod
    def _find_chat_spans(distro_exporter: SpanCapturingExporter) -> list[ReadableSpan]:
        """Find exported spans that have gen_ai.input.messages."""
        get_tracer_provider().force_flush()
        time.sleep(0.5)
        return [s for s in distro_exporter.spans if s.attributes and GEN_AI_INPUT_MESSAGES_KEY in s.attributes]

    @pytest.mark.asyncio
    async def test_simple_chat_message_mapping(
        self, llm: AzureChatOpenAI, distro_exporter: SpanCapturingExporter
    ) -> None:
        """Simple chat: capture LangChain message format on exported spans."""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content="You are a helpful assistant. Reply in one sentence."),
            HumanMessage(content="What is the capital of France?"),
        ]

        result = await llm.ainvoke(messages)
        assert result is not None
        assert len(result.content) > 0

        chat_spans = self._find_chat_spans(distro_exporter)
        assert len(chat_spans) > 0, f"No chat spans found. All spans: {[s.name for s in distro_exporter.spans]}"

        print(f"\n=== All exported spans ({len(distro_exporter.spans)}) ===")
        for s in distro_exporter.spans:
            attrs = dict(s.attributes or {})
            print(f"  {s.name} | attrs: {list(attrs.keys())}")

        attrs = dict(chat_spans[-1].attributes or {})

        # --- Input messages ---
        raw_input = attrs[GEN_AI_INPUT_MESSAGES_KEY]
        print(f"\n=== gen_ai.input.messages ===\n{raw_input}")
        input_data = json.loads(raw_input)

        # Verify structure (plain array format per OTel spec)
        if isinstance(input_data, list) and len(input_data) > 0 and isinstance(input_data[0], dict):
            # Structured A365 array format (list of message dicts)
            for msg in input_data:
                assert "role" in msg
                assert "parts" in msg
            print("\n  ✓ Structured A365 array format detected")
            messages_list = input_data
        elif isinstance(input_data, dict) and "messages" in input_data:
            messages_list = input_data["messages"]
            for msg in messages_list:
                assert "role" in msg
                assert "parts" in msg
            print("\n  ✓ Structured A365 format detected")
        else:
            # Plain string list or other raw format (pre-mapper)
            messages_list = input_data
            flat_text = ""
            for item in input_data if isinstance(input_data, list) else []:
                if isinstance(item, str):
                    flat_text += item.lower()
                elif isinstance(item, dict):
                    for part in item.get("parts", []):
                        if isinstance(part, dict) and "content" in part:
                            flat_text += part["content"].lower()
            assert "capital" in flat_text, f"Expected 'capital' in input messages content, got: {input_data}"
            print("\n  → List format (pre-mapper)")

        # --- Output messages ---
        raw_output = attrs.get(GEN_AI_OUTPUT_MESSAGES_KEY)
        assert raw_output is not None, "gen_ai.output.messages not found"
        print(f"\n=== gen_ai.output.messages ===\n{raw_output}")
        output_data = json.loads(raw_output)

        if isinstance(output_data, list) and len(output_data) > 0 and isinstance(output_data[0], dict):
            for msg in output_data:
                assert msg["role"] == "assistant"
                assert any(p["type"] == "text" for p in msg["parts"])
            print("\n  ✓ Structured A365 array format detected")
        elif isinstance(output_data, dict) and "messages" in output_data:
            for msg in output_data["messages"]:
                assert msg["role"] == "assistant"
                assert any(p["type"] == "text" for p in msg["parts"])
            print("\n  ✓ Structured A365 format detected")
        elif isinstance(output_data, list) and len(output_data) > 0:
            # Plain string list (pre-mapper)
            assert all(isinstance(item, str) for item in output_data)
            print("\n  → Raw string list format (pre-mapper)")

    @pytest.mark.asyncio
    async def test_tool_call_message_mapping(
        self, llm: AzureChatOpenAI, distro_exporter: SpanCapturingExporter
    ) -> None:
        """Tool-calling chat: capture tool_call parts in LangChain spans."""
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.tools import tool

        @tool
        def get_weather(city: str) -> str:
            """Get the current weather for a city."""
            return f"The weather in {city} is sunny, 22°C."

        llm_with_tools = llm.bind_tools([get_weather])

        messages = [
            SystemMessage(content="You are a weather assistant. Always use the get_weather tool."),
            HumanMessage(content="What's the weather in Seattle?"),
        ]

        result = await llm_with_tools.ainvoke(messages)
        assert result is not None

        chat_spans = self._find_chat_spans(distro_exporter)
        assert len(chat_spans) > 0

        print(f"\n=== All exported spans ({len(distro_exporter.spans)}) ===")
        for s in distro_exporter.spans:
            attrs = dict(s.attributes or {})
            op = attrs.get(GEN_AI_OPERATION_NAME_KEY, "(none)")
            print(f"  {s.name} | op={op} | attrs: {list(attrs.keys())}")

        # Check all spans for message content
        for span in chat_spans:
            attrs = dict(span.attributes or {})
            for key in (GEN_AI_INPUT_MESSAGES_KEY, GEN_AI_OUTPUT_MESSAGES_KEY):
                raw = attrs.get(key)
                if raw:
                    print(f"\n--- {span.name} | {key} ---\n{raw}")
