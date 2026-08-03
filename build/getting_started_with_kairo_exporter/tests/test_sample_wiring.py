from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys
from unittest.mock import MagicMock

SAMPLE_SRC = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SAMPLE_SRC))

from services.guardrail_service import (
    BLOCKED_RESPONSE,
    DENY_TRIGGER,
    SAMPLE_INPUT_VALUE,
)
from services.message_pipeline import GuardrailContext, handle_message_turn
from utils.observability_helpers import create_request_details
from utils.sample_exporter_flags import (
    CANONICAL_EXPORTER_ENV_VAR,
    LEGACY_EXPORTER_ENV_VAR,
    align_exporter_env_flags,
)


class FakeInvokeScope:
    def __init__(self) -> None:
        self.recorded_inputs: list[list[str]] = []

    def record_input_messages(self, messages: list[str]) -> None:
        self.recorded_inputs.append(messages)


@dataclass(frozen=True)
class FakeToken:
    token: str


def test_create_request_details_uses_fixed_non_sensitive_content():
    request = create_request_details(session_id="conversation-789")

    assert request.content == SAMPLE_INPUT_VALUE
    assert request.session_id == "conversation-789"


def test_on_message_denied_path_blocks_downstream_runtime():
    invoke_scope = FakeInvokeScope()
    sent_messages: list[str] = []
    logger = MagicMock()

    async def send_activity(message: str) -> None:
        sent_messages.append(message)

    async def exchange_token() -> FakeToken:
        raise AssertionError("Denied path must not exchange tokens.")

    def cache_token(_tenant_id: str, _agent_id: str, _token: str) -> None:
        raise AssertionError("Denied path must not cache tokens.")

    async def execute_tool(_tool_name: str, _arguments: str) -> str:
        raise AssertionError("Denied path must not execute tools.")

    async def call_llm(_message: str) -> str:
        raise AssertionError("Denied path must not call the LLM.")

    result = asyncio.run(
        handle_message_turn(
            user_message=f"Please process {DENY_TRIGGER}",
            guardrail_context=GuardrailContext(
                agent_id="agent-123",
                agent_name="Kairo Guardrail Sample",
                tenant_id="tenant-456",
                conversation_id="conversation-789",
            ),
            invoke_scope=invoke_scope,
            send_activity=send_activity,
            exchange_token=exchange_token,
            cache_token=cache_token,
            execute_tool=execute_tool,
            call_llm=call_llm,
            logger=logger,
        )
    )

    assert result is None
    assert invoke_scope.recorded_inputs == [[SAMPLE_INPUT_VALUE]]
    assert sent_messages == [BLOCKED_RESPONSE]
    logger.info.assert_not_called()


def test_allowed_path_logs_only_non_sensitive_sample_value():
    invoke_scope = FakeInvokeScope()
    sent_messages: list[str] = []
    logger = MagicMock()
    live_user_message = "What is the weather in Seattle?"
    observed_messages: list[str] = []

    async def send_activity(message: str) -> None:
        sent_messages.append(message)

    async def exchange_token() -> FakeToken:
        return FakeToken("sample-token")

    def cache_token(_tenant_id: str, _agent_id: str, _token: str) -> None:
        return None

    async def execute_tool(tool_name: str, arguments: str) -> str:
        assert tool_name == "get_weather"
        assert arguments == "current location"
        return "Weather information for current location: Sunny, 72°F"

    async def call_llm(message: str) -> str:
        observed_messages.append(message)
        return "Sunny and warm."

    result = asyncio.run(
        handle_message_turn(
            user_message=live_user_message,
            guardrail_context=GuardrailContext(
                agent_id="agent-123",
                agent_name="Kairo Guardrail Sample",
                tenant_id="tenant-456",
                conversation_id="conversation-789",
            ),
            invoke_scope=invoke_scope,
            send_activity=send_activity,
            exchange_token=exchange_token,
            cache_token=cache_token,
            execute_tool=execute_tool,
            call_llm=call_llm,
            logger=logger,
        )
    )

    assert result == "Sunny and warm."
    assert invoke_scope.recorded_inputs == [[SAMPLE_INPUT_VALUE]]
    assert sent_messages == ["Sunny and warm."]
    assert observed_messages == [
        f"{live_user_message}\n\nTool result: Weather information for current location: Sunny, 72°F"
    ]
    logger.info.assert_called_once_with(
        "Processing user message with sample observability content: %s",
        SAMPLE_INPUT_VALUE,
    )
    assert live_user_message not in str(logger.mock_calls)


def test_align_exporter_env_flags_prefers_canonical_and_sets_legacy_alias():
    environment = {
        CANONICAL_EXPORTER_ENV_VAR: "false",
        LEGACY_EXPORTER_ENV_VAR: "true",
    }

    align_exporter_env_flags(environment)

    assert environment[CANONICAL_EXPORTER_ENV_VAR] == "false"
    assert environment[LEGACY_EXPORTER_ENV_VAR] == "false"
