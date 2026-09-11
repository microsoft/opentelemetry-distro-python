# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import importlib
import json

import pytest


def test_execute_tool_arguments_serialize_with_schema_names():
    schema = importlib.import_module("microsoft.opentelemetry.a365.core.models.tool_call_schema")

    payload = schema.ExecuteToolCallArguments(
        action="read",
        resources=[
            schema.ToolCallResource(
                resource_id="file-1",
                uri="https://example/file",
                name="report",
                resource_type="file",
                provider="sharepoint",
                identifiers=[schema.ToolCallIdentifier(identifier_type="drive_id", value="d1")],
                container=schema.ToolCallContainer(
                    container_id="site-1",
                    uri="https://example",
                    container_type="site",
                ),
            )
        ],
        parameters={"page": 1},
    )

    assert json.loads(schema.serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "action": "read",
        "resources": [
            {
                "id": "file-1",
                "uri": "https://example/file",
                "name": "report",
                "type": "file",
                "provider": "sharepoint",
                "identifiers": [{"type": "drive_id", "value": "d1"}],
                "container": {"id": "site-1", "uri": "https://example", "type": "site"},
            }
        ],
        "parameters": {"page": 1},
    }


def test_execute_tool_arguments_omit_none_and_preserve_empty_or_false_values():
    schema = importlib.import_module("microsoft.opentelemetry.a365.core.models.tool_call_schema")

    payload = schema.ExecuteToolCallArguments(
        resources=[],
        parameters={
            "include_archived": False,
            "page": 0,
            "filters": {},
            "tags": [],
        },
        extension_data={"provider_options": {}},
    )

    assert json.loads(schema.serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "resources": [],
        "parameters": {
            "include_archived": False,
            "page": 0,
            "filters": {},
            "tags": [],
        },
        "provider_options": {},
    }


def test_execute_tool_arguments_reject_extension_property_collisions():
    schema = importlib.import_module("microsoft.opentelemetry.a365.core.models.tool_call_schema")

    with pytest.raises(ValueError, match="action"):
        schema.serialize_tool_call_payload(
            schema.ExecuteToolCallArguments(action="read", extension_data={"action": "write"})
        )
