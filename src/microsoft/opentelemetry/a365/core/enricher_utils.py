# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared utilities for A365 span enrichers.

Provides content extraction helpers used by framework-specific enrichers
(Agent Framework, Semantic Kernel, LangChain) to convert structured OTel
messages to plain content arrays before A365 export.
"""

from __future__ import annotations

import json


def _extract_text_from_message(msg: dict, role_filter: str | None) -> list[str]:
    """Extract text content strings from a single structured message dict."""
    role = msg.get("role", "")
    if role_filter and role != role_filter:
        return []
    parts = msg.get("parts")
    if not parts or not isinstance(parts, list):
        return []
    return [
        part["content"] for part in parts if isinstance(part, dict) and part.get("type") == "text" and "content" in part
    ]


def extract_content_as_string_list(messages_json: str, role_filter: str | None = None) -> str:
    """Extract content values from messages JSON and return as JSON string list.

    Handles the OTel structured message format with ``"parts"`` arrays.
    Only extracts text content, ignoring tool_call and tool_call_response parts.

    Args:
        messages_json: JSON string of messages.
        role_filter: If provided, only extract content from messages with this role.

    Returns:
        JSON string containing only the text content values as an array,
        or the original string if parsing fails.
    """
    try:
        messages = json.loads(messages_json)
        if isinstance(messages, list):
            # If already a plain list of strings, return as-is
            if all(isinstance(item, str) for item in messages):
                return messages_json
            contents = []
            for msg in messages:
                if isinstance(msg, dict):
                    contents.extend(_extract_text_from_message(msg, role_filter))
            return json.dumps(contents)
        return messages_json
    except (json.JSONDecodeError, TypeError):
        return messages_json


def extract_input_content(messages_json: str) -> str:
    """Extract text content from user messages only."""
    return extract_content_as_string_list(messages_json, role_filter="user")


def extract_output_content(messages_json: str) -> str:
    """Extract only assistant text content from output messages."""
    return extract_content_as_string_list(messages_json, role_filter="assistant")
