# InvokeAgent Semantic Convention Alignment

## Goal

Align the new `InvokeAgentScope` request and response parameter API with the
current OpenTelemetry GenAI semantic conventions before the API is released.

## Cache-write token naming

The current OpenTelemetry GenAI registry defines
`gen_ai.usage.cache_write.input_tokens` as the number of input tokens written
to a provider-managed cache. The PR's `cache_creation` name is provider
terminology and must not be exposed as the OpenTelemetry attribute name.

Rename the new response model field, constants, emitted attribute, tests, and
documentation from `cache_creation` to `cache_write`:

- `cache_creation_input_tokens` becomes `cache_write_input_tokens`.
- `GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY` becomes
  `GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS_KEY`.
- `gen_ai.usage.cache_creation.input_tokens` becomes
  `gen_ai.usage.cache_write.input_tokens`.

This change applies only to the new `InvokeAgentScope` API introduced by the
PR. Existing provider adapters may continue reading provider-specific fields
named `cache_creation_input_tokens`, but their exported semantic attribute
names are outside this PR's scope.

## Structured system instructions

OpenTelemetry defines `gen_ai.system_instructions` as an array of structured
parts. The public request model will therefore use:

```python
system_instructions: Sequence[TextPart] | None = None
```

Callers pass a list or tuple of the existing `TextPart` objects:

```python
system_instructions=[
    TextPart(content="Be concise."),
    TextPart(content="Return JSON."),
]
```

`TextPart` automatically supplies the `"type": "text"` discriminator. The span
attribute will contain a JSON-encoded representation of the OpenTelemetry
array because the OpenTelemetry Python span API cannot directly store
structured objects:

```json
[{"content":"Be concise.","type":"text"},{"content":"Return JSON.","type":"text"}]
```

Plain strings will no longer be accepted by this new, unreleased field. This
keeps the public API aligned with the semantic convention from its first
release rather than establishing a non-compliant compatibility contract.

## Serialization

Add a focused serializer for system-instruction parts in the existing message
utility module. It will reuse the same dataclass conversion, enum handling,
`None` omission, JSON encoding, logging, and non-throwing telemetry behavior as
the existing message serializers.

The request-recording path will omit the attribute when instructions are
`None`. Otherwise, it will serialize the sequence and set
`gen_ai.system_instructions` to the resulting JSON string.

## Tests and documentation

Tests will verify:

- Cache-write tokens use the new model field and standard emitted key.
- The obsolete cache-creation key is not emitted.
- One and multiple `TextPart` instructions serialize to the expected JSON
  array with automatic `type: "text"` fields.
- Unset instructions remain omitted.
- Serialization failure follows the repository's non-throwing telemetry
  behavior.

README and A365 guide examples will use `TextPart` objects and the cache-write
terminology. The two GitHub review threads will receive concise replies
referencing the implementation commit and will be resolved after validation.

## Validation

Run the targeted A365 InvokeAgent tests, formatting and static checks covering
the changed modules, and `git diff --check`. Push the implementation to the PR
branch only after those checks pass.
