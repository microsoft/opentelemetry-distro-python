# Execute-Tool Metadata Wrapper Design

## Summary

Execute-tool schema models currently flatten provider-specific extension entries into
the containing JSON object. This permits extension keys to collide with declared
schema properties such as `action`, bypassing typed validation when the declared
property is omitted.

Provider-specific values will instead serialize under a dedicated `metadata` JSON
property. The change applies to every currently extensible execute-tool object.
Existing language-specific public property names remain unchanged to preserve source
compatibility.

## Goals

- Prevent provider extensions from overwriting or bypassing declared schema fields.
- Give provider-specific values an explicit namespace in the wire contract.
- Preserve existing Python, .NET, and JavaScript public property names.
- Use the same `metadata` JSON representation in every language implementation.
- Avoid adding empty `metadata` objects to existing payloads.

## Non-Goals

- Renaming existing public extension properties.
- Adding a setter or builder API for individual metadata entries.
- Defining provider-specific metadata keys or values.
- Supporting both flattened and wrapped extension output simultaneously.

## Public API

Public model signatures remain unchanged.

Python continues to expose:

```python
extension_data: dict[str, object] = field(default_factory=dict)
```

.NET continues to expose:

```csharp
public IDictionary<string, object?> AdditionalProperties { get; set; }
```

JavaScript retains its existing extension-data property name.

Callers continue assigning provider-specific values through those properties. No
additional setter method is required because the existing dictionaries support
constructor assignment and later mutation.

## Wire Contract

A non-empty extension dictionary serializes as the declared JSON property
`metadata`. The entries are not flattened into the containing object.

For example, this Python input:

```python
ExecuteToolCallArguments(
    action=ToolCallAction.READ,
    parameters={},
    extension_data={
        "provider_trace_id": "trace-789",
        "tenant_id": "tenant-123",
    },
)
```

serializes as:

```json
{
  "schema_version": "1.0",
  "action": "read",
  "parameters": {},
  "metadata": {
    "provider_trace_id": "trace-789",
    "tenant_id": "tenant-123"
  }
}
```

When the extension dictionary is empty, `metadata` is omitted:

```json
{
  "schema_version": "1.0",
  "action": "read",
  "parameters": {}
}
```

## Model Scope

The wrapper applies independently at every currently extensible object:

- `ExecuteToolCallArguments`
- `ToolCallResource`
- `ToolCallIdentifier`
- `ToolCallContainer`
- `ExecuteToolCallResult`
- `ToolCallResultOutcome`
- `ToolCallResultSensitivity`
- `ToolCallResultPolicy`
- `ToolCallResultSecurity`
- `ToolCallResultPagination`
- `ToolCallResultResource`

Each object's extension dictionary becomes that object's `metadata` property. For
example:

```json
{
  "resources": [
    {
      "id": "resource-id",
      "metadata": {
        "tenant_id": "tenant-123"
      },
      "container": {
        "id": "container-id",
        "metadata": {
          "site_collection_id": "site-456"
        }
      }
    }
  ],
  "metadata": {
    "provider_trace_id": "trace-789"
  }
}
```

## Serialization Behavior

The Python serializer will treat `extension_data` as a normal declared model field
whose JSON name is `metadata`. It will recursively serialize the dictionary using the
existing non-throwing diagnostic behavior.

The .NET implementation will stop using `[JsonExtensionData]` for
`AdditionalProperties` and map that property to `metadata` instead. JavaScript will
perform the equivalent explicit property mapping.

An extension dictionary entry named `metadata` is valid because it remains nested:

```json
{
  "metadata": {
    "metadata": "provider-defined value"
  }
}
```

It cannot overwrite the outer declared `metadata` property.

## Compatibility and Rollout

Public source APIs remain compatible, but the serialized wire format changes from
flattened properties to a `metadata` wrapper. Python, .NET, JavaScript, the published
schema, and downstream parsers must adopt the new representation as one coordinated
contract change.

Consumers must not depend on provider-specific properties appearing at the same level
as declared schema fields. During rollout, producers and consumers should be released
in an order that prevents new wrapped payloads from reaching parsers that reject the
`metadata` property.

## Error Handling

The existing serializer contract remains in effect:

- Invalid extension containers produce the repository-standard diagnostic payload.
- A failure in a metadata value does not throw from telemetry instrumentation.
- Cycles and unsupported values follow existing safe-serialization behavior.
- Declared enum fields continue to use typed validation and cannot be supplied through
  metadata as top-level replacements.

## Testing

Tests must verify:

- Non-empty extension dictionaries serialize under `metadata`.
- Empty extension dictionaries omit `metadata`.
- Metadata is wrapped at the root and at every nested extensible model.
- Keys matching declared schema fields remain inside `metadata` and cannot replace the
  declared fields.
- Existing safe serialization behavior applies recursively to metadata values.
- Raw dictionary and string payload support remains unchanged.
- Scope and ETW integrations emit the same wrapped representation.
- Documentation examples match the new contract.

## Documentation

Update the execute-tool schema documentation and usage examples to describe
provider-specific metadata as a nested `metadata` object. The documentation must note
that language SDK property names may differ while the JSON contract consistently uses
`metadata`.
