# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""String constants for guardrail target types."""


class GuardrailTargetType:
    """Well-known guardrail target type values.

    Users may also supply custom string values not listed here.
    """

    LLM_INPUT = "llm_input"
    LLM_OUTPUT = "llm_output"
    TOOL_CALL = "tool_call"
    TOOL_DEFINITION = "tool_definition"
    MEMORY_STORE = "memory_store"
    MEMORY_RETRIEVE = "memory_retrieve"
    KNOWLEDGE_QUERY = "knowledge_query"
    KNOWLEDGE_RESULT = "knowledge_result"
    MESSAGE = "message"
