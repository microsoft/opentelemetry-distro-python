# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class ToolCallIdentifier:
    """Resource identifier for an execute-tool payload."""

    identifier_type: str | None = field(default=None, metadata={"json_name": "type"})
    value: str | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallContainer:
    """Container that owns or scopes an execute-tool resource."""

    container_id: str | None = field(default=None, metadata={"json_name": "id"})
    uri: str | None = None
    container_type: str | None = field(default=None, metadata={"json_name": "type"})
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolCallResource:
    """Resource referenced by an execute-tool arguments payload."""

    resource_id: str | None = field(default=None, metadata={"json_name": "id"})
    uri: str | None = None
    name: str | None = None
    resource_type: str | None = field(default=None, metadata={"json_name": "type"})
    provider: str | None = None
    identifiers: list[ToolCallIdentifier] | None = None
    container: ToolCallContainer | None = None
    extension_data: dict[str, object] = field(default_factory=dict)


@dataclass
class ExecuteToolCallArguments:
    """Structured arguments for an execute-tool call."""

    action: str | None = None
    resources: list[ToolCallResource] | None = None
    parameters: dict[str, object] | None = None
    schema_version: str = field(default="1.0", metadata={"json_name": "schema_version"})
    extension_data: dict[str, object] = field(default_factory=dict)


def serialize_tool_call_payload(value: ExecuteToolCallArguments) -> str:
    """Serialize a typed execute-tool payload using the Agent365 JSON contract."""

    return json.dumps(_to_json_value(value), ensure_ascii=False)


def _to_json_value(value: Any) -> Any:
    if value is None:
        return None

    if is_dataclass(value):
        serialized: dict[str, object] = {}
        extension_data: Mapping[str, object] | None = None
        for item in fields(value):
            item_value = getattr(value, item.name)
            if item.name == "extension_data":
                extension_data = item_value
                continue
            if item_value is None:
                continue
            json_name = item.metadata.get("json_name", item.name)
            serialized[json_name] = _to_json_value(item_value)

        if extension_data:
            for key, item_value in extension_data.items():
                if key in serialized:
                    raise ValueError(f"Extension data cannot overwrite model property '{key}'.")
                serialized[key] = _to_json_value(item_value)
        return serialized

    if isinstance(value, Mapping):
        return {key: _to_json_value(item_value) for key, item_value in value.items()}

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_json_value(item_value) for item_value in value]

    return value
