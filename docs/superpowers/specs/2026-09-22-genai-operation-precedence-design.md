# GenAI Operation Classification Precedence

## Goal

Prevent a span whose name identifies one supported GenAI operation from being
classified as another operation solely because it inherits
`gen_ai.operation.name` baggage.

## Classification precedence

When `A365SpanProcessor.on_start()` classifies a span:

1. An explicit `gen_ai.operation.name` span attribute remains authoritative.
2. A recognized operation in the span name takes precedence over operation
   baggage.
3. A recognized baggage operation is used only when the span name does not
   identify a supported operation.
4. Known initial span names and supported instrumentation scopes continue to
   identify GenAI spans without assigning a modeled operation when appropriate.

This changes only the relative precedence of recognized span names and baggage.
It preserves explicit attribute precedence, custom baggage propagation, and
scope-based GenAI classification.

## Regression coverage

Add a processor test for an `execute_tool ...` span created under context that
contains `gen_ai.operation.name=invoke_agent`, invoke-only caller baggage, and
an opted-in custom baggage key. The test must verify:

- invoke-only caller and endpoint attributes are not copied to the tool span;
- the opted-in custom attribute is still copied because the span remains GenAI;
- existing tests continue to cover baggage inference when the span name does
  not identify an operation.

## Scope

The change is limited to the GenAI span classifier and focused processor tests.
No baggage-builder API, metadata format, or public API changes are required.
