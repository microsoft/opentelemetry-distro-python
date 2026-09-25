# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import datetime
import json
import uuid
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum

import pytest

from microsoft.opentelemetry.a365.core.models.tool_call_schema import (
    TOOL_CALL_SCHEMA_VERSION,
    TOOL_CALL_SERIALIZATION_ERROR_JSON,
    ExecuteToolCallArguments,
    ExecuteToolCallResult,
    ToolCallAction,
    ToolCallContainer,
    ToolCallIdentifier,
    ToolCallOutcomeStatus,
    ToolCallResource,
    ToolCallResultOutcome,
    ToolCallResultPagination,
    ToolCallResultPolicy,
    ToolCallResultResource,
    ToolCallResultSecurity,
    ToolCallResultSensitivity,
    ToolPolicyDecision,
    serialize_tool_call_payload,
)

# Exact diagnostic contract emitted by the .NET distro (MessageUtils.SerializeToolPayload).
DOTNET_SERIALIZATION_ERROR = '{"serialization_error":"Failed to serialize execute tool payload."}'


class _OtherEnum(str, Enum):
    READ = "read"


class _ThrowingMapping(Mapping):
    """Mapping whose enumeration fails, mirroring the .NET ThrowingEnumerable test double."""

    def __getitem__(self, key):
        raise RuntimeError("test")

    def __iter__(self):
        raise RuntimeError("test")

    def __len__(self):
        return 1


def test_serialization_error_matches_dotnet_contract():
    assert TOOL_CALL_SERIALIZATION_ERROR_JSON == DOTNET_SERIALIZATION_ERROR
    assert json.loads(TOOL_CALL_SERIALIZATION_ERROR_JSON) == {
        "serialization_error": "Failed to serialize execute tool payload."
    }


def test_schema_version_default_matches_dotnet_contract():
    assert TOOL_CALL_SCHEMA_VERSION == "1.0"
    assert ExecuteToolCallArguments().schema_version == "1.0"
    assert ExecuteToolCallResult().schema_version == "1.0"


def test_public_enums_match_dotnet_values():
    assert [member.value for member in ToolCallAction] == ["create", "read", "update", "delete"]
    assert [member.value for member in ToolCallOutcomeStatus] == ["success", "failure"]
    assert [member.value for member in ToolPolicyDecision] == ["allow", "deny"]
    assert ToolCallAction.READ == "read"


def test_execute_tool_arguments_serialize_with_schema_names():
    payload = ExecuteToolCallArguments(
        action=ToolCallAction.READ,
        resources=[
            ToolCallResource(
                resource_id="file-1",
                uri="https://example/file",
                name="report",
                resource_type="file",
                provider="sharepoint",
                identifiers=[
                    ToolCallIdentifier(
                        identifier_type="drive_id",
                        value="d1",
                        extension_data={"identifier_scope": "tenant"},
                    )
                ],
                container=ToolCallContainer(
                    container_id="site-1",
                    uri="https://example",
                    container_type="site",
                    extension_data={"site_collection_id": "site-456"},
                ),
                extension_data={"tenant_id": "tenant-123"},
            )
        ],
        parameters={"page": 1},
        extension_data={"provider_trace_id": "trace-789"},
    )

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "action": "read",
        "resources": [
            {
                "id": "file-1",
                "uri": "https://example/file",
                "name": "report",
                "type": "file",
                "provider": "sharepoint",
                "identifiers": [
                    {
                        "type": "drive_id",
                        "value": "d1",
                        "metadata": {"identifier_scope": "tenant"},
                    }
                ],
                "container": {
                    "id": "site-1",
                    "uri": "https://example",
                    "type": "site",
                    "metadata": {"site_collection_id": "site-456"},
                },
                "metadata": {"tenant_id": "tenant-123"},
            }
        ],
        "parameters": {"page": 1},
        "metadata": {"provider_trace_id": "trace-789"},
    }


def test_execute_tool_result_serializes_with_schema_names():
    payload = ExecuteToolCallResult(
        outcome=ToolCallResultOutcome(
            status=ToolCallOutcomeStatus.SUCCESS,
            code="ok",
            provider_code="sharepoint_ok",
            message="Read completed",
            extension_data={"outcome_detail": "accepted"},
        ),
        resources=[
            ToolCallResultResource(
                resource_id="file-1",
                uri="https://example/file",
                name="report",
                resource_type="file",
                provider="sharepoint",
                identifiers=[
                    ToolCallIdentifier(
                        identifier_type="drive_id",
                        value="d1",
                        extension_data={"identifier_scope": "tenant"},
                    )
                ],
                container=ToolCallContainer(
                    container_id="site-1",
                    uri="https://example",
                    container_type="site",
                    extension_data={"site_collection_id": "site-456"},
                ),
                outcome=ToolCallResultOutcome(
                    status=ToolCallOutcomeStatus.SUCCESS,
                    extension_data={"resource_outcome": "accepted"},
                ),
                sensitivity=ToolCallResultSensitivity(
                    label_id="confidential",
                    extension_data={"label_source": "provider"},
                ),
                policy=ToolCallResultPolicy(
                    decision=ToolPolicyDecision.ALLOW,
                    policy_id="policy-1",
                    name="Sharing policy",
                    extension_data={"policy_version": "2"},
                ),
                security=ToolCallResultSecurity(
                    xpia_detected=False,
                    extension_data={"scanner": "provider"},
                ),
                data={"bytes": 0},
                extension_data={"resource_region": "westus"},
            )
        ],
        data={"content": ""},
        pagination=ToolCallResultPagination(
            has_more=False,
            next_cursor="cursor-2",
            total_count=0,
            extension_data={"page_source": "cache"},
        ),
        extension_data={"provider_trace_id": "trace-789"},
    )

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "outcome": {
            "status": "success",
            "code": "ok",
            "provider_code": "sharepoint_ok",
            "message": "Read completed",
            "metadata": {"outcome_detail": "accepted"},
        },
        "resources": [
            {
                "id": "file-1",
                "uri": "https://example/file",
                "name": "report",
                "type": "file",
                "provider": "sharepoint",
                "identifiers": [
                    {
                        "type": "drive_id",
                        "value": "d1",
                        "metadata": {"identifier_scope": "tenant"},
                    }
                ],
                "container": {
                    "id": "site-1",
                    "uri": "https://example",
                    "type": "site",
                    "metadata": {"site_collection_id": "site-456"},
                },
                "outcome": {
                    "status": "success",
                    "metadata": {"resource_outcome": "accepted"},
                },
                "sensitivity": {
                    "label_id": "confidential",
                    "metadata": {"label_source": "provider"},
                },
                "policy": {
                    "decision": "allow",
                    "id": "policy-1",
                    "name": "Sharing policy",
                    "metadata": {"policy_version": "2"},
                },
                "security": {
                    "xpia_detected": False,
                    "metadata": {"scanner": "provider"},
                },
                "data": {"bytes": 0},
                "metadata": {"resource_region": "westus"},
            }
        ],
        "data": {"content": ""},
        "pagination": {
            "has_more": False,
            "next_cursor": "cursor-2",
            "total_count": 0,
            "metadata": {"page_source": "cache"},
        },
        "metadata": {"provider_trace_id": "trace-789"},
    }


def test_execute_tool_arguments_omit_none_properties_and_preserve_empty_or_false_values():
    payload = ExecuteToolCallArguments(
        resources=[],
        parameters={
            "include_archived": False,
            "page": 0,
            "filters": {},
            "tags": [],
        },
        extension_data={"provider_options": {}},
    )

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "resources": [],
        "parameters": {
            "include_archived": False,
            "page": 0,
            "filters": {},
            "tags": [],
        },
        "metadata": {"provider_options": {}},
    }


def test_none_is_omitted_for_model_properties_but_preserved_inside_mappings_and_lists():
    payload = ExecuteToolCallResult(
        outcome=ToolCallResultOutcome(
            status=ToolCallOutcomeStatus.SUCCESS,
            provider_code=None,
            extension_data={"provider_outcome": None, "attempts": 0},
        ),
        data={"content": None, "matches": [None, 1]},
        extension_data={"provider_result": None, "cached": False},
    )

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "outcome": {
            "status": "success",
            "metadata": {"provider_outcome": None, "attempts": 0},
        },
        "data": {"content": None, "matches": [None, 1]},
        "metadata": {"provider_result": None, "cached": False},
    }


def test_extension_data_keys_matching_declared_fields_remain_inside_metadata():
    payload = ExecuteToolCallArguments(
        action=ToolCallAction.READ,
        extension_data={
            "action": "write",
            "schema_version": "9.9",
        },
    )

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "action": "read",
        "metadata": {
            "action": "write",
            "schema_version": "9.9",
        },
    }


def test_nested_extension_data_keys_matching_declared_fields_remain_inside_metadata():
    payload = ExecuteToolCallResult(
        outcome=ToolCallResultOutcome(
            code="ok",
            extension_data={"code": "provider-code"},
        ),
    )

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "outcome": {
            "code": "ok",
            "metadata": {"code": "provider-code"},
        },
    }


def test_empty_extension_data_omits_metadata():
    assert json.loads(serialize_tool_call_payload(ExecuteToolCallArguments())) == {"schema_version": "1.0"}


def test_serialize_none_payload_returns_none():
    assert serialize_tool_call_payload(None) is None


def test_serialize_is_non_throwing_for_unsupported_values():
    payload = ExecuteToolCallResult(extension_data={"good": 42, "bad": object()})

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_serialize_is_non_throwing_when_a_single_value_raises():
    payload = ExecuteToolCallResult(extension_data={"good": 42, "bad": _ThrowingMapping()})

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_serialize_is_non_throwing_for_excessively_nested_payloads():
    nested: dict[str, object] = {}
    node = nested
    for _ in range(10_000):
        child: dict[str, object] = {}
        node["child"] = child
        node = child

    assert serialize_tool_call_payload(ExecuteToolCallResult(data=nested)) == DOTNET_SERIALIZATION_ERROR


def test_serialize_is_non_throwing_for_self_referencing_payloads():
    payload = ExecuteToolCallResult()
    payload.extension_data["self"] = payload

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_serialize_is_non_throwing_for_nested_mapping_cycles():
    cycle: dict[str, object] = {}
    cycle["self"] = cycle

    assert serialize_tool_call_payload(ExecuteToolCallResult(data=cycle)) == DOTNET_SERIALIZATION_ERROR


def test_serialize_is_non_throwing_for_nested_list_cycles():
    cycle: list[object] = []
    cycle.append(cycle)

    payload = ExecuteToolCallResult(data={"items": cycle})

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_repeated_references_that_are_not_cycles_still_serialize():
    shared = {"shared": True}
    payload = ExecuteToolCallResult(data={"first": shared, "second": shared})

    assert json.loads(serialize_tool_call_payload(payload)) == {
        "schema_version": "1.0",
        "data": {"first": {"shared": True}, "second": {"shared": True}},
    }


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_serialize_is_non_throwing_for_non_finite_floats(value):
    payload = ExecuteToolCallResult(data={"good": 42, "bad": value})

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_serialize_is_non_throwing_for_non_string_mapping_keys():
    payload = ExecuteToolCallResult(data={1: "one"})  # type: ignore[dict-item]

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_bytes_serialize_as_base64_like_dotnet():
    payload = ExecuteToolCallResult(data={"bytes": bytes([0, 1, 2, 3]), "buffer": bytearray([0, 1, 2, 3])})

    assert json.loads(serialize_tool_call_payload(payload))["data"] == {
        "bytes": "AAECAw==",
        "buffer": "AAECAw==",
    }


def test_well_known_scalar_types_serialize_as_strings_or_numbers():
    identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")
    payload = ExecuteToolCallResult(
        data={
            "timestamp": datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc),
            "day": datetime.date(2026, 1, 2),
            "time": datetime.time(3, 4, 5),
            "id": identifier,
            "amount": Decimal("1.5"),
        }
    )

    assert json.loads(serialize_tool_call_payload(payload))["data"] == {
        "timestamp": "2026-01-02T03:04:05Z",
        "day": "2026-01-02",
        "time": "03:04:05",
        "id": "12345678-1234-5678-1234-567812345678",
        "amount": 1.5,
    }


def test_decimal_serialization_preserves_precision():
    amount = Decimal("12345678901234567890.1234")
    payload = ExecuteToolCallResult(data={"amount": amount})

    serialized = serialize_tool_call_payload(payload)

    assert serialized is not None
    assert json.loads(serialized, parse_float=Decimal)["data"]["amount"] == amount


def test_enum_values_inside_mappings_serialize_to_their_values():
    payload = ExecuteToolCallResult(data={"action": ToolCallAction.READ, "status": ToolCallOutcomeStatus.FAILURE})

    assert json.loads(serialize_tool_call_payload(payload))["data"] == {
        "action": "read",
        "status": "failure",
    }


def test_tuples_serialize_as_json_arrays():
    payload = ExecuteToolCallResult(data={"items": (1, 2)})

    assert json.loads(serialize_tool_call_payload(payload))["data"] == {"items": [1, 2]}


def test_sets_and_views_serialize_as_json_arrays_like_dotnet_collections():
    payload = ExecuteToolCallResult(
        data={
            "scopes": {"read"},
            "frozen": frozenset(["write"]),
            "keys": {"a": 1}.keys(),
            "values": {"a": 1}.values(),
        }
    )

    assert json.loads(serialize_tool_call_payload(payload))["data"] == {
        "scopes": ["read"],
        "frozen": ["write"],
        "keys": ["a"],
        "values": [1],
    }


def test_generators_are_not_supported():
    payload = ExecuteToolCallResult(data={"items": (index for index in range(2))})

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (ExecuteToolCallArguments(action=ToolCallAction.UPDATE), {"action": "update"}),
        (ExecuteToolCallArguments(action="update"), {"action": "update"}),
    ],
)
def test_enum_fields_accept_members_and_exact_lowercase_strings(payload, expected):
    assert json.loads(serialize_tool_call_payload(payload))["action"] == expected["action"]


@pytest.mark.parametrize("value", ["Read", "READ", "reed", "", 0, 1, True, _OtherEnum.READ, ["read"]])
def test_action_rejects_undefined_and_non_string_values(value):
    payload = ExecuteToolCallArguments(action=value)

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


@pytest.mark.parametrize("value", ["Success", "ok", 0, 1, True])
def test_outcome_status_rejects_undefined_and_non_string_values(value):
    payload = ExecuteToolCallResult(outcome=ToolCallResultOutcome(status=value))

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


@pytest.mark.parametrize("value", ["Allow", "permit", 0, 1, True])
def test_policy_decision_rejects_undefined_and_non_string_values(value):
    payload = ExecuteToolCallResult(
        resources=[ToolCallResultResource(policy=ToolCallResultPolicy(decision=value))],
    )

    assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR


def test_outcome_status_accepts_exact_lowercase_strings():
    payload = ExecuteToolCallResult(outcome=ToolCallResultOutcome(status="failure"))

    assert json.loads(serialize_tool_call_payload(payload))["outcome"] == {"status": "failure"}


def test_policy_decision_accepts_exact_lowercase_strings():
    payload = ExecuteToolCallResult(
        resources=[ToolCallResultResource(policy=ToolCallResultPolicy(decision="deny"))],
    )

    assert json.loads(serialize_tool_call_payload(payload))["resources"] == [{"policy": {"decision": "deny"}}]


def test_serialization_failure_is_logged(caplog):
    payload = ExecuteToolCallResult(extension_data={"bad": object()})

    with caplog.at_level("WARNING", logger="microsoft.opentelemetry.a365.core.models.tool_call_schema"):
        assert serialize_tool_call_payload(payload) == DOTNET_SERIALIZATION_ERROR

    assert any("Failed to serialize execute tool payload" in record.message for record in caplog.records)
