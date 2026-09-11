# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed Agent365 execute-tool argument and result schema models.

The models mirror the Agent365 JSON contract used by the .NET distro. Payloads are
serialized with :func:`serialize_tool_call_payload`, which never raises: any failure is
replaced by :data:`TOOL_CALL_SERIALIZATION_ERROR_JSON` so a span is never orphaned and no
caller exception escapes the telemetry path.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

#: Schema version emitted on every typed execute-tool payload.
TOOL_CALL_SCHEMA_VERSION = "1.0"

#: Diagnostic payload emitted when a typed execute-tool payload cannot be serialized.
TOOL_CALL_SERIALIZATION_ERROR_JSON = '{"serialization_error":"Failed to serialize execute tool payload."}'

_JSON_NAME = "json_name"
_ENUM_TYPE = "enum_type"
_EXTENSION_DATA_FIELD = "extension_data"


class ToolCallAction(str, Enum):
    """Well-known actions taken by an execute-tool call."""

    #: Creates a resource.
    CREATE = "create"
    #: Reads a resource.
    READ = "read"
    #: Updates a resource.
    UPDATE = "update"
    #: Deletes a resource.
    DELETE = "delete"


class ToolCallOutcomeStatus(str, Enum):
    """Well-known statuses for an execute-tool outcome."""

    #: The tool call completed successfully.
    SUCCESS = "success"
    #: The tool call failed.
    FAILURE = "failure"


class ToolPolicyDecision(str, Enum):
    """Well-known policy decisions for an execute-tool result resource."""

    #: The policy allows the tool call.
    ALLOW = "allow"
    #: The policy denies the tool call.
    DENY = "deny"


@dataclass
class ToolCallIdentifier:
    """Resource identifier for an execute-tool payload."""

    identifier_type: str | None = field(default=None, metadata={_JSON_NAME: "type"})
    value: str | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallContainer:
    """Container that owns or scopes an execute-tool resource."""

    container_id: str | None = field(default=None, metadata={_JSON_NAME: "id"})
    uri: str | None = None
    container_type: str | None = field(default=None, metadata={_JSON_NAME: "type"})
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResource:
    """Resource referenced by an execute-tool arguments payload."""

    resource_id: str | None = field(default=None, metadata={_JSON_NAME: "id"})
    uri: str | None = None
    name: str | None = None
    resource_type: str | None = field(default=None, metadata={_JSON_NAME: "type"})
    provider: str | None = None
    identifiers: list[ToolCallIdentifier] | None = None
    container: ToolCallContainer | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ExecuteToolCallArguments:
    """Structured arguments for an execute-tool call."""

    action: ToolCallAction | str | None = field(default=None, metadata={_ENUM_TYPE: ToolCallAction})
    resources: list[ToolCallResource] | None = None
    parameters: dict[str, object] | None = None
    schema_version: str = TOOL_CALL_SCHEMA_VERSION
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResultOutcome:
    """Outcome metadata for an execute-tool result."""

    status: ToolCallOutcomeStatus | str | None = field(default=None, metadata={_ENUM_TYPE: ToolCallOutcomeStatus})
    code: str | None = None
    provider_code: str | None = None
    message: str | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResultSensitivity:
    """Sensitivity metadata for an execute-tool result resource."""

    label_id: str | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResultPolicy:
    """Policy metadata for an execute-tool result resource."""

    decision: ToolPolicyDecision | str | None = field(default=None, metadata={_ENUM_TYPE: ToolPolicyDecision})
    policy_id: str | None = field(default=None, metadata={_JSON_NAME: "id"})
    name: str | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResultSecurity:
    """Security metadata for an execute-tool result resource."""

    xpia_detected: bool | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResultPagination:
    """Pagination metadata for an execute-tool result."""

    has_more: bool | None = None
    next_cursor: str | None = None
    total_count: int | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResultResource:
    """Resource included in an execute-tool result payload."""

    resource_id: str | None = field(default=None, metadata={_JSON_NAME: "id"})
    uri: str | None = None
    name: str | None = None
    resource_type: str | None = field(default=None, metadata={_JSON_NAME: "type"})
    provider: str | None = None
    identifiers: list[ToolCallIdentifier] | None = None
    container: ToolCallContainer | None = None
    outcome: ToolCallResultOutcome | None = None
    sensitivity: ToolCallResultSensitivity | None = None
    policy: ToolCallResultPolicy | None = None
    security: ToolCallResultSecurity | None = None
    data: dict[str, object] | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ExecuteToolCallResult:
    """Structured result for an execute-tool call."""

    outcome: ToolCallResultOutcome | None = None
    resources: list[ToolCallResultResource] | None = None
    data: dict[str, object] | None = None
    pagination: ToolCallResultPagination | None = None
    schema_version: str = TOOL_CALL_SCHEMA_VERSION
    extension_data: dict[str, object] = field(default_factory=dict)


ToolCallPayload = ExecuteToolCallArguments | ExecuteToolCallResult


def _to_base64(value: bytes | bytearray | memoryview) -> str:
    """Return the base64 text for a binary value, matching the .NET byte-array contract."""
    return base64.b64encode(bytes(value)).decode("ascii")


def _to_isoformat(value: datetime.datetime | datetime.date | datetime.time) -> str:
    """Return the ISO-8601 text for a date/time value."""
    return value.isoformat()


# Ordered scalar conversions; ``bool`` must precede ``int`` and ``str`` must precede ``Sequence``.
_SCALAR_CONVERTERS: tuple[tuple[type | tuple[type, ...], Callable[[Any], Any]], ...] = (
    (str, str),
    (bool, bool),
    (int, int),
    (float, float),
    ((bytes, bytearray, memoryview), _to_base64),
    ((datetime.datetime, datetime.date, datetime.time), _to_isoformat),
    (uuid.UUID, str),
    (Decimal, float),
)


def serialize_tool_call_payload(value: ToolCallPayload | None) -> str | None:
    """Serialize a typed execute-tool payload using the Agent365 JSON contract.

    The call never raises. When any value in the payload cannot be represented in the
    schema — an unsupported type, a reference cycle, a non-finite float, an undefined
    enum value, or extension data colliding with a serialized model property — the whole
    payload is replaced by :data:`TOOL_CALL_SERIALIZATION_ERROR_JSON`.

    Args:
        value: The typed payload to serialize, or ``None``.

    Returns:
        The JSON payload, the diagnostic payload on failure, or ``None`` when
        ``value`` is ``None``.
    """
    if value is None:
        return None

    try:
        return json.dumps(_to_json_value(value, set()), ensure_ascii=False, allow_nan=False)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to serialize execute tool payload: %r", exc)
        return TOOL_CALL_SERIALIZATION_ERROR_JSON


def _to_json_value(value: Any, stack: set[int]) -> Any:
    """Convert a payload value into a JSON-compatible value, raising on unsupported input."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return _to_json_value(value.value, stack)
    for scalar_types, convert in _SCALAR_CONVERTERS:
        if isinstance(value, scalar_types):
            return convert(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _dataclass_to_json_value(value, stack)
    if isinstance(value, Mapping):
        return _mapping_to_json_value(value, stack)
    if isinstance(value, Sequence):
        return _sequence_to_json_value(value, stack)
    raise TypeError(f"Object of type {type(value).__name__} is not supported in an execute tool payload.")


def _enter(value: Any, stack: set[int]) -> int:
    """Push a container onto the active recursion path, rejecting reference cycles."""
    marker = id(value)
    if marker in stack:
        raise ValueError("Circular reference detected in execute tool payload.")
    stack.add(marker)
    return marker


def _dataclass_to_json_value(value: Any, stack: set[int]) -> dict[str, Any]:
    """Serialize a schema model, omitting ``None`` properties and merging extension data."""
    marker = _enter(value, stack)
    try:
        serialized: dict[str, Any] = {}
        extension_data: Any = {}
        for item in fields(value):
            item_value = getattr(value, item.name)
            if item.name == _EXTENSION_DATA_FIELD:
                extension_data = item_value if item_value is not None else {}
                continue
            if item_value is None:
                continue
            json_name = item.metadata.get(_JSON_NAME, item.name)
            enum_type = item.metadata.get(_ENUM_TYPE)
            if enum_type is None:
                serialized[json_name] = _to_json_value(item_value, stack)
            else:
                serialized[json_name] = _coerce_enum(item_value, enum_type, json_name)

        if not isinstance(extension_data, Mapping):
            raise TypeError(f"Extension data must be a mapping; got {type(extension_data).__name__}.")

        for key, item_value in extension_data.items():
            json_key = _json_object_key(key)
            if json_key in serialized:
                raise ValueError(f"Extension data cannot overwrite execute tool payload property '{json_key}'.")
            serialized[json_key] = _to_json_value(item_value, stack)
        return serialized
    finally:
        stack.discard(marker)


def _mapping_to_json_value(value: Mapping[Any, Any], stack: set[int]) -> dict[str, Any]:
    """Serialize a caller-supplied mapping, preserving ``None`` values as JSON ``null``."""
    marker = _enter(value, stack)
    try:
        return {_json_object_key(key): _to_json_value(item_value, stack) for key, item_value in value.items()}
    finally:
        stack.discard(marker)


def _sequence_to_json_value(value: Sequence[Any], stack: set[int]) -> list[Any]:
    """Serialize a caller-supplied sequence, preserving ``None`` items as JSON ``null``."""
    marker = _enter(value, stack)
    try:
        return [_to_json_value(item_value, stack) for item_value in value]
    finally:
        stack.discard(marker)


def _json_object_key(key: Any) -> str:
    """Return the JSON object key for a mapping key, rejecting non-string keys."""
    key_value = key.value if isinstance(key, Enum) else key
    if not isinstance(key_value, str):
        raise TypeError(f"Execute tool payload object keys must be strings; got {type(key).__name__}.")
    return str(key_value)


def _coerce_enum(value: Any, enum_type: type[Enum], json_name: str) -> str:
    """Return the schema token for an enum-valued property.

    Enum members are accepted, as are the exact lowercase string tokens for backward
    compatibility. Undefined tokens, numeric values, booleans, and members of other
    enums are rejected so schema-invalid data is never emitted.
    """
    if isinstance(value, enum_type):
        member_value = value.value
    elif isinstance(value, str) and not isinstance(value, Enum):
        try:
            member_value = enum_type(value).value
        except ValueError as exc:
            raise ValueError(f"'{json_name}' must be one of {_allowed_enum_values(enum_type)}; got {value!r}.") from exc
    else:
        raise TypeError(
            f"'{json_name}' must be a {enum_type.__name__} member or one of "
            f"{_allowed_enum_values(enum_type)}; got {type(value).__name__}."
        )
    if not isinstance(member_value, str):
        raise TypeError(f"'{json_name}' must serialize to a string; got {type(member_value).__name__}.")
    return str(member_value)


def _allowed_enum_values(enum_type: type[Enum]) -> str:
    """Return a display list of the accepted string tokens for an enum."""
    return ", ".join(repr(member.value) for member in enum_type)
