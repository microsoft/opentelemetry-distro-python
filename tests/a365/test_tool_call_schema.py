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

    with pytest.raises(ValueError, match="action"):
        schema.serialize_tool_call_payload(schema.ExecuteToolCallArguments(extension_data={"action": "write"}))


def test_execute_tool_payload_omits_none_values_recursively():
    schema = importlib.import_module("microsoft.opentelemetry.a365.core.models.tool_call_schema")

    payload = schema.ExecuteToolCallResult(
        outcome=schema.ToolCallResultOutcome(
            status="success",
            provider_code=None,
            extension_data={"provider_outcome": None, "attempts": 0},
        ),
        data={"content": None, "matches": []},
        extension_data={"provider_result": None, "cached": False},
    )

    assert json.loads(schema.serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "outcome": {"status": "success", "attempts": 0},
        "data": {"matches": []},
        "cached": False,
    }


def test_execute_tool_result_serializes_with_schema_names():
    schema = importlib.import_module("microsoft.opentelemetry.a365.core.models.tool_call_schema")

    payload = schema.ExecuteToolCallResult(
        outcome=schema.ToolCallResultOutcome(
            status="success",
            code="ok",
            provider_code="sharepoint_ok",
            message="Read completed",
        ),
        resources=[
            schema.ToolCallResultResource(
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
                outcome=schema.ToolCallResultOutcome(status="success"),
                sensitivity=schema.ToolCallResultSensitivity(label_id="confidential"),
                policy=schema.ToolCallResultPolicy(
                    decision="allow",
                    policy_id="policy-1",
                    name="Sharing policy",
                ),
                security=schema.ToolCallResultSecurity(xpia_detected=False),
                data={"bytes": 0},
            )
        ],
        data={"content": ""},
        pagination=schema.ToolCallResultPagination(
            has_more=False,
            next_cursor="cursor-2",
            total_count=0,
        ),
    )

    assert json.loads(schema.serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "outcome": {
            "status": "success",
            "code": "ok",
            "provider_code": "sharepoint_ok",
            "message": "Read completed",
        },
        "resources": [
            {
                "id": "file-1",
                "uri": "https://example/file",
                "name": "report",
                "type": "file",
                "provider": "sharepoint",
                "identifiers": [{"type": "drive_id", "value": "d1"}],
                "container": {"id": "site-1", "uri": "https://example", "type": "site"},
                "outcome": {"status": "success"},
                "sensitivity": {"label_id": "confidential"},
                "policy": {"decision": "allow", "id": "policy-1", "name": "Sharing policy"},
                "security": {"xpia_detected": False},
                "data": {"bytes": 0},
            }
        ],
        "data": {"content": ""},
        "pagination": {"has_more": False, "next_cursor": "cursor-2", "total_count": 0},
    }
