from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Protocol

from microsoft.opentelemetry.a365.core import AgentDetails, Request

from services.guardrail_service import (
    GuardrailResult,
    SAMPLE_INPUT_VALUE,
    evaluate_input_guardrail,
)


class SupportsRecordInputMessages(Protocol):
    def record_input_messages(self, messages: list[str]) -> None: ...


@dataclass(frozen=True)
class GuardrailContext:
    agent_id: str
    agent_name: str
    tenant_id: str
    conversation_id: str | None


async def handle_message_turn(
    *,
    user_message: str,
    guardrail_context: GuardrailContext,
    invoke_scope: SupportsRecordInputMessages,
    send_activity: Callable[[str], Awaitable[None]],
    exchange_token: Callable[[], Awaitable[object]],
    cache_token: Callable[[str, str, str], None],
    execute_tool: Callable[[str, str], Awaitable[str]],
    call_llm: Callable[[str], Awaitable[str]],
    logger: logging.Logger | None = None,
    observability_input_value: str = SAMPLE_INPUT_VALUE,
    guardrail_evaluator: Callable[[str, AgentDetails, Request], GuardrailResult] = evaluate_input_guardrail,
) -> str | None:
    invoke_scope.record_input_messages([observability_input_value])

    guardrail_result = guardrail_evaluator(
        user_message=user_message,
        agent_details=AgentDetails(
            agent_id=guardrail_context.agent_id,
            agent_name=guardrail_context.agent_name,
            tenant_id=guardrail_context.tenant_id,
        ),
        request=Request(conversation_id=guardrail_context.conversation_id),
    )
    if not guardrail_result.allowed:
        if guardrail_result.response_message is not None:
            await send_activity(guardrail_result.response_message)
        return None

    exaau_token = await exchange_token()
    cache_token(
        guardrail_context.tenant_id,
        guardrail_context.agent_id,
        exaau_token.token,
    )

    if logger is not None:
        logger.info(
            "Processing user message with sample observability content: %s",
            observability_input_value,
        )

    tool_result = None
    lowered_message = user_message.lower()
    if "weather" in lowered_message:
        tool_result = await execute_tool("get_weather", "current location")
    elif "calculate" in lowered_message or "math" in lowered_message:
        tool_result = await execute_tool("calculate", "2 + 2")

    enhanced_message = user_message
    if tool_result:
        enhanced_message = f"{user_message}\n\nTool result: {tool_result}"

    ai_response = await call_llm(enhanced_message)
    await send_activity(ai_response)
    return ai_response
