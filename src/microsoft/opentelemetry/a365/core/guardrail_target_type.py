# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""String constants for guardrail target types."""


class GuardrailTargetType:
    """Well-known guardrail target type values.

    Users may also supply custom string values not listed here.
    """

    #: A guardrail evaluated against model input.
    LLM_INPUT = "llm_input"
    #: A guardrail evaluated against model output.
    LLM_OUTPUT = "llm_output"
    #: A guardrail evaluated against a tool call.
    TOOL_CALL = "tool_call"
    #: A guardrail evaluated against a tool definition.
    TOOL_DEFINITION = "tool_definition"
    #: A guardrail evaluated when writing to a memory store.
    MEMORY_STORE = "memory_store"
    #: A guardrail evaluated when reading from a memory store.
    MEMORY_RETRIEVE = "memory_retrieve"
    #: A guardrail evaluated against a knowledge query.
    KNOWLEDGE_QUERY = "knowledge_query"
    #: A guardrail evaluated against a knowledge result.
    KNOWLEDGE_RESULT = "knowledge_result"
    #: A guardrail evaluated against a message.
    MESSAGE = "message"
