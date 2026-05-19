# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Span enricher for LangChain.

Maps standard OTel GenAI attributes to A365-specific keys before export.
Registered by LangChainInstrumentor when the A365 pipeline is available.
"""

from microsoft.opentelemetry.a365.core.constants import (
    EXECUTE_TOOL_OPERATION_NAME,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
    GEN_AI_TOOL_ARGS_KEY,
    GEN_AI_TOOL_CALL_RESULT_KEY,
    INVOKE_AGENT_OPERATION_NAME,
    SESSION_ID_KEY,
)
from microsoft.opentelemetry.a365.core.exporters.enriched_span import EnrichedReadableSpan
from opentelemetry.sdk.trace import ReadableSpan


def enrich_langchain_span(span: ReadableSpan) -> ReadableSpan:
    """Enricher function for LangChain spans.

    Transforms standard OTel GenAI attributes to A365-specific keys:
    - ``gen_ai.conversation.id`` → ``microsoft.session.id``
    - For invoke_agent spans: extracts content from input/output messages
    - For execute_tool spans: maps tool arguments and results
    """
    extra_attributes = {}
    attributes = span.attributes or {}

    # Map gen_ai.conversation.id → microsoft.session.id for A365 consumers
    conversation_id = attributes.get(GEN_AI_CONVERSATION_ID_KEY)
    if conversation_id and SESSION_ID_KEY not in attributes:
        extra_attributes[SESSION_ID_KEY] = str(conversation_id)

    if span.name.startswith(INVOKE_AGENT_OPERATION_NAME):
        input_messages = attributes.get(GEN_AI_INPUT_MESSAGES_KEY)
        if input_messages:
            extra_attributes[GEN_AI_INPUT_MESSAGES_KEY] = str(input_messages)

        output_messages = attributes.get(GEN_AI_OUTPUT_MESSAGES_KEY)
        if output_messages:
            extra_attributes[GEN_AI_OUTPUT_MESSAGES_KEY] = str(output_messages)

    elif span.name.startswith(EXECUTE_TOOL_OPERATION_NAME):
        if GEN_AI_TOOL_ARGS_KEY in attributes:
            extra_attributes[GEN_AI_TOOL_ARGS_KEY] = str(attributes[GEN_AI_TOOL_ARGS_KEY])

        if GEN_AI_TOOL_CALL_RESULT_KEY in attributes:
            extra_attributes[GEN_AI_TOOL_CALL_RESULT_KEY] = str(attributes[GEN_AI_TOOL_CALL_RESULT_KEY])

    if extra_attributes:
        return EnrichedReadableSpan(span, extra_attributes)

    return span
