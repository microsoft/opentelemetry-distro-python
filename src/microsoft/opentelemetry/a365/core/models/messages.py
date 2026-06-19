# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""OTEL gen-ai semantic convention message types.

Defines the structured message format for input/output message tracing,
following the OpenTelemetry gen-ai semantic conventions:

* https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-input-messages.json
* https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-output-messages.json
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MessageRole(Enum):
    """Role of a message participant per OTEL gen-ai semantic conventions."""

    #: System / developer instructions that set up the conversation.
    SYSTEM = "system"
    #: Input authored by the end user.
    USER = "user"
    #: Output produced by the model.
    ASSISTANT = "assistant"
    #: Output of a tool returned back to the model.
    TOOL = "tool"


class FinishReason(Enum):
    """Reason a model stopped generating per OTEL gen-ai semantic conventions."""

    #: The model emitted a natural stop point or a provided stop sequence.
    STOP = "stop"
    #: Generation stopped because the maximum token limit was reached.
    LENGTH = "length"
    #: Generation stopped because content was filtered by a safety system.
    CONTENT_FILTER = "content_filter"
    #: The model stopped to request a tool call.
    TOOL_CALL = "tool_call"
    #: Generation stopped because an error occurred.
    ERROR = "error"


class Modality(Enum):
    """Media modality for blob, file, and URI parts."""

    #: Image content.
    IMAGE = "image"
    #: Video content.
    VIDEO = "video"
    #: Audio content.
    AUDIO = "audio"


# ---------------------------------------------------------------------------
# Message part types (discriminated on ``type``)
# ---------------------------------------------------------------------------


@dataclass
class TextPart:
    """Plain text content."""

    content: str
    type: str = field(default="text", init=False)


@dataclass
class ToolCallRequestPart:
    """A tool call requested by the model."""

    name: str
    id: str | None = None
    arguments: dict[str, object] | list[object] | str | None = None
    type: str = field(default="tool_call", init=False)


@dataclass
class ToolCallResponsePart:
    """Result of a tool call."""

    id: str | None = None
    response: object | None = None
    type: str = field(default="tool_call_response", init=False)


@dataclass
class ReasoningPart:
    """Model reasoning / chain-of-thought content."""

    content: str
    type: str = field(default="reasoning", init=False)


@dataclass
class BlobPart:
    """Inline binary data (base64-encoded)."""

    modality: Modality | str
    content: str
    mime_type: str | None = None
    type: str = field(default="blob", init=False)


@dataclass
class FilePart:
    """Reference to a pre-uploaded file."""

    modality: Modality | str
    file_id: str
    mime_type: str | None = None
    type: str = field(default="file", init=False)


@dataclass
class UriPart:
    """External URI reference."""

    modality: Modality | str
    uri: str
    mime_type: str | None = None
    type: str = field(default="uri", init=False)


@dataclass
class ServerToolCallPart:
    """Server-side tool invocation."""

    name: str
    server_tool_call: dict[str, object]
    id: str | None = None
    type: str = field(default="server_tool_call", init=False)


@dataclass
class ServerToolCallResponsePart:
    """Server-side tool response."""

    server_tool_call_response: dict[str, object]
    id: str | None = None
    type: str = field(default="server_tool_call_response", init=False)


@dataclass
class GenericPart:
    """Extensible part for custom / future types."""

    type: str
    data: dict[str, object] = field(default_factory=dict)


MessagePart = Union[
    TextPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
    ReasoningPart,
    BlobPart,
    FilePart,
    UriPart,
    ServerToolCallPart,
    ServerToolCallResponsePart,
    GenericPart,
]
"""Union of all message part types per OTEL gen-ai semantic conventions."""


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------


@dataclass
class ChatMessage:
    """An input message sent to a model (OTEL gen-ai semantic conventions)."""

    role: MessageRole
    parts: list[MessagePart] = field(default_factory=list)
    name: str | None = None


@dataclass
class OutputMessage(ChatMessage):
    """An output message produced by a model (OTEL gen-ai semantic conventions).

    ``finish_reason`` defaults to ``"stop"`` per OTel spec when not provided.
    """

    finish_reason: str | None = "stop"

    def __post_init__(self) -> None:
        """Coerce None finish_reason to default."""
        if self.finish_reason is None:
            self.finish_reason = "stop"


# ---------------------------------------------------------------------------
# Message containers
# ---------------------------------------------------------------------------


@dataclass
class InputMessages:
    """Container for input messages. Serializes as a plain JSON array per OTel spec."""

    messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class OutputMessages:
    """Container for output messages. Serializes as a plain JSON array per OTel spec."""

    messages: list[OutputMessage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parameter type aliases (backward-compatible union types)
# ---------------------------------------------------------------------------

InputMessagesParam = Union[str, list[str], InputMessages]
"""Accepted input for ``record_input_messages``.

Supports a single string, a list of strings (backward compat), or the structured
container.
"""

OutputMessagesParam = Union[str, list[str], OutputMessages]
"""Accepted input for ``record_output_messages``.

Supports a single string, a list of strings (backward compat), or the structured
container.
"""
