# Execute-Tool Metadata Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialize every execute-tool model's existing `extension_data` dictionary under a non-empty `metadata` JSON wrapper instead of flattening its entries.

**Architecture:** Preserve all Python public dataclass signatures and change only the shared dataclass serializer's wire mapping. Unit tests establish wrapping, omission, nesting, collision isolation, and safe-serialization behavior; scope integration tests verify emitted telemetry attributes; documentation defines the coordinated cross-language contract.

**Tech Stack:** Python 3.10+, dataclasses, `json`, pytest, unittest, OpenTelemetry span attributes.

## Global Constraints

- Keep `extension_data: dict[str, object] = field(default_factory=dict)` unchanged on every Python model.
- Serialize non-empty extension dictionaries under the JSON key `metadata`.
- Omit `metadata` when the extension dictionary is empty or `None`.
- Apply the wrapper independently to every currently extensible execute-tool model.
- Do not emit flattened extension keys.
- Preserve existing non-throwing diagnostic serialization behavior.
- Preserve raw dictionary and string argument/result behavior.
- Coordinate the `metadata` wire format with .NET, JavaScript, the published schema, and downstream parsers.

---

### Task 1: Wrap Schema Model Extension Data

**Files:**
- Modify: `tests/a365/test_tool_call_schema.py:70-285`
- Modify: `src/microsoft/opentelemetry/a365/core/models/tool_call_schema.py:25-30`
- Modify: `src/microsoft/opentelemetry/a365/core/models/tool_call_schema.py:269-298`

**Interfaces:**
- Consumes: Existing model field `extension_data: dict[str, object]`.
- Produces: `serialize_tool_call_payload(payload: ToolCallPayload | None) -> str | None` output containing `metadata` for non-empty extension dictionaries.

- [ ] **Step 1: Update the argument serialization test to require nested metadata**

In `test_execute_tool_arguments_serialize_with_schema_names`, add extension data at the arguments, resource, identifier, and container levels:

```python
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
```

Require the corresponding portions of the expected dictionary to be:

```python
{
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
```

- [ ] **Step 2: Update the result serialization test to cover every result-side extensible model**

Add extension data to the existing result tree:

```python
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
            identifiers=[
                ToolCallIdentifier(
                    identifier_type="drive_id",
                    value="d1",
                    extension_data={"identifier_scope": "tenant"},
                )
            ],
            container=ToolCallContainer(
                container_id="site-1",
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
                extension_data={"policy_version": "2"},
            ),
            security=ToolCallResultSecurity(
                xpia_detected=False,
                extension_data={"scanner": "provider"},
            ),
            extension_data={"resource_region": "westus"},
        )
    ],
    pagination=ToolCallResultPagination(
        has_more=False,
        extension_data={"page_source": "cache"},
    ),
    extension_data={"provider_trace_id": "trace-789"},
)
```

Assert each extension dictionary appears under `metadata` at its owning object:

```python
serialized = json.loads(serialize_tool_call_payload(payload))

assert serialized["metadata"] == {"provider_trace_id": "trace-789"}
assert serialized["outcome"]["metadata"] == {"outcome_detail": "accepted"}
resource = serialized["resources"][0]
assert resource["metadata"] == {"resource_region": "westus"}
assert resource["identifiers"][0]["metadata"] == {"identifier_scope": "tenant"}
assert resource["container"]["metadata"] == {"site_collection_id": "site-456"}
assert resource["outcome"]["metadata"] == {"resource_outcome": "accepted"}
assert resource["sensitivity"]["metadata"] == {"label_source": "provider"}
assert resource["policy"]["metadata"] == {"policy_version": "2"}
assert resource["security"]["metadata"] == {"scanner": "provider"}
assert serialized["pagination"]["metadata"] == {"page_source": "cache"}
```

- [ ] **Step 3: Replace collision tests with isolation and omission tests**

Replace the four tests beginning with
`test_extension_data_may_supply_a_key_whose_model_property_is_none` through
`test_extension_data_collision_is_detected_on_nested_models` with:

```python
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
    assert json.loads(serialize_tool_call_payload(ExecuteToolCallArguments())) == {
        "schema_version": "1.0"
    }
```

Update the existing preservation tests so their expected output contains:

```python
"metadata": {"provider_options": {}}
```

and:

```python
"outcome": {
    "status": "success",
    "metadata": {"provider_outcome": None, "attempts": 0},
},
"metadata": {"provider_result": None, "cached": False},
```

- [ ] **Step 4: Run the focused tests and verify they fail**

Run:

```powershell
python -m pytest tests\a365\test_tool_call_schema.py -q
```

Expected: failures show extension keys such as `provider_trace_id`, `action`, and `provider_options` are still flattened and no `metadata` object is emitted.

- [ ] **Step 5: Add the metadata JSON-name constant**

Near `_EXTENSION_DATA_FIELD`, add:

```python
_EXTENSION_DATA_JSON_NAME = "metadata"
```

- [ ] **Step 6: Replace extension-data merging with wrapped serialization**

Replace `_dataclass_to_json_value` with:

```python
def _dataclass_to_json_value(value: Any, stack: set[int]) -> dict[str, Any]:
    """Serialize a schema model, omitting ``None`` properties and wrapping extension data."""
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
        if extension_data:
            serialized[_EXTENSION_DATA_JSON_NAME] = _mapping_to_json_value(extension_data, stack)
        return serialized
    finally:
        stack.discard(marker)
```

- [ ] **Step 7: Run the schema tests and verify they pass**

Run:

```powershell
python -m pytest tests\a365\test_tool_call_schema.py -q
```

Expected: all tests pass, including unsupported-value, throwing-mapping, cycle, enum, collection, and scalar conversion cases.

- [ ] **Step 8: Commit the serializer and unit tests**

```powershell
git add src\microsoft\opentelemetry\a365\core\models\tool_call_schema.py tests\a365\test_tool_call_schema.py
git commit -m "fix: wrap execute-tool extension data"
```

---

### Task 2: Verify Telemetry Integration

**Files:**
- Modify: `tests/a365/test_execute_tool_scope.py:39-118`

**Interfaces:**
- Consumes: `serialize_tool_call_payload()` metadata-wrapper output from Task 1.
- Produces: Span attributes `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` containing the same wrapped JSON.

- [ ] **Step 1: Add extension data to the typed arguments scope test**

Update `test_typed_arguments_include_schema_version`:

```python
arguments=ExecuteToolCallArguments(
    action=ToolCallAction.READ,
    resources=[
        ToolCallResource(
            resource_id="file-1",
            extension_data={"tenant_id": "tenant-123"},
        )
    ],
    extension_data={"provider_trace_id": "trace-789"},
),
```

Add these assertions:

```python
self.assertEqual(payload["metadata"], {"provider_trace_id": "trace-789"})
self.assertEqual(
    payload["resources"],
    [{"id": "file-1", "metadata": {"tenant_id": "tenant-123"}}],
)
```

- [ ] **Step 2: Add extension data to the typed result scope test**

Update `test_typed_result_include_schema_version`:

```python
scope.record_response(
    ExecuteToolCallResult(
        outcome=ToolCallResultOutcome(
            status=ToolCallOutcomeStatus.SUCCESS,
            extension_data={"provider_status": "accepted"},
        ),
        data={"count": 0},
        extension_data={"provider_trace_id": "trace-789"},
    )
)
```

Add these assertions:

```python
self.assertEqual(payload["metadata"], {"provider_trace_id": "trace-789"})
self.assertEqual(
    payload["outcome"],
    {
        "status": "success",
        "metadata": {"provider_status": "accepted"},
    },
)
```

- [ ] **Step 3: Run the scope tests**

Run:

```powershell
python -m pytest tests\a365\test_execute_tool_scope.py -q
```

Expected: all scope tests pass; raw dictionary/string payload tests remain unchanged.

- [ ] **Step 4: Run the combined targeted suite**

Run:

```powershell
python -m pytest tests\a365\test_tool_call_schema.py tests\a365\test_execute_tool_scope.py -q
```

Expected: all targeted schema and integration tests pass.

- [ ] **Step 5: Commit the integration coverage**

```powershell
git add tests\a365\test_execute_tool_scope.py
git commit -m "test: cover execute-tool metadata telemetry"
```

---

### Task 3: Document the Metadata Wire Contract

**Files:**
- Modify: `A365_DOCUMENTATION.md:386-488`
- Modify: `README.md:73-91`
- Modify: `CHANGELOG.md:2-8`

**Interfaces:**
- Consumes: The `metadata` wire behavior implemented in Tasks 1 and 2.
- Produces: User-facing examples and release notes that distinguish public `extension_data` from JSON `metadata`.

- [ ] **Step 1: Update the full A365 JSON example**

In `A365_DOCUMENTATION.md`, change:

```json
"provider_operation": "weather.lookup"
```

to:

```json
"metadata": {
  "provider_operation": "weather.lookup"
}
```

- [ ] **Step 2: Replace the extension-data behavior explanation**

Replace the existing merging/collision paragraphs with:

```markdown
`extension_data` is serialized under a `metadata` property on the same model. The public Python field name
remains `extension_data`, while the JSON wire contract consistently uses `metadata`. Empty extension
dictionaries omit `metadata`.

Each extensible nested model owns its own metadata object. Extension keys therefore cannot replace declared
properties such as `action`, `schema_version`, `outcome.status`, or `policy.decision`; a matching extension key
remains inside `metadata`.
```

Remove `extension-data collision` from the serialization-failure list because matching keys are now isolated,
not rejected.

- [ ] **Step 3: Clarify the README example**

After the typed-arguments code sample in `README.md`, add:

```markdown
The Python `extension_data` dictionary is emitted as a non-empty `metadata` object in the JSON payload,
preventing provider-specific keys from colliding with declared schema fields.
```

- [ ] **Step 4: Update the changelog entry**

Change the feature description to:

```markdown
- Add typed Agent365 execute-tool argument and result schema models with `schema_version: "1.0"` serialization,
  `ToolCallAction`/`ToolCallOutcomeStatus`/`ToolPolicyDecision` enums, provider extension data wrapped under
  the JSON `metadata` property, public exports, and `ExecuteToolScope` support while preserving raw
  dict/string payloads. Execute-tool payload serialization is non-throwing: unserializable payloads record
  `{"serialization_error": "Failed to serialize execute tool payload."}` instead of failing the span.
```

- [ ] **Step 5: Run formatting and targeted validation**

Run:

```powershell
python -m black --check src\microsoft\opentelemetry\a365\core\models\tool_call_schema.py tests\a365\test_tool_call_schema.py tests\a365\test_execute_tool_scope.py
python -m pytest tests\a365\test_tool_call_schema.py tests\a365\test_execute_tool_scope.py -q
```

Expected: Black reports no changes required and all targeted tests pass.

- [ ] **Step 6: Commit the documentation**

```powershell
git add A365_DOCUMENTATION.md README.md CHANGELOG.md
git commit -m "docs: describe execute-tool metadata wrapper"
```

---

### Task 4: Final Verification

**Files:**
- Verify: `src/microsoft/opentelemetry/a365/core/models/tool_call_schema.py`
- Verify: `tests/a365/test_tool_call_schema.py`
- Verify: `tests/a365/test_execute_tool_scope.py`
- Verify: `A365_DOCUMENTATION.md`
- Verify: `README.md`
- Verify: `CHANGELOG.md`

**Interfaces:**
- Consumes: All implementation, tests, and documentation from Tasks 1-3.
- Produces: A review-ready Python PR whose public API remains stable and whose wire contract uses `metadata`.

- [ ] **Step 1: Run the complete A365 unit-test directory**

```powershell
python -m pytest tests\a365 -q --ignore=tests\a365\integration
```

Expected: all A365 unit tests pass.

- [ ] **Step 2: Run static checks for the changed Python files**

```powershell
python -m black --check src\microsoft\opentelemetry\a365\core\models\tool_call_schema.py tests\a365\test_tool_call_schema.py tests\a365\test_execute_tool_scope.py
python -m pylint src\microsoft\opentelemetry\a365\core\models\tool_call_schema.py tests\a365\test_tool_call_schema.py tests\a365\test_execute_tool_scope.py
python -m mypy --python-version 3.10 --show-error-codes --ignore-missing-imports src\microsoft\opentelemetry\a365\core\models\tool_call_schema.py
```

Expected: Black, Pylint, and Mypy exit successfully.

- [ ] **Step 3: Inspect the final diff**

```powershell
git diff fork/copilot/execute-tool-schema...HEAD --check
git status --short
```

Expected: no whitespace errors and no uncommitted files.

- [ ] **Step 4: Confirm cross-language rollout dependency in the PR description**

Update the PR description's summary or compatibility note to state:

```markdown
The JSON wire contract now wraps provider-specific extension values under `metadata`. The corresponding
.NET, JavaScript, schema, and downstream parser updates must roll out as a coordinated contract change.
```

- [ ] **Step 5: Commit only if the PR-description note is also tracked in repository documentation**

If Step 4 required no repository changes, do not create an empty commit. If repository documentation was
adjusted during final review, stage only those exact files and commit:

```powershell
git commit -m "docs: note metadata rollout requirements"
```
