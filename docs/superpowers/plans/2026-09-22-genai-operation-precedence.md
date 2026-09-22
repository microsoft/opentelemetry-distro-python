# GenAI Operation Precedence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent inherited operation baggage from overriding a supported GenAI operation identified by the span name.

**Architecture:** Keep explicit `gen_ai.operation.name` span attributes authoritative. When the attribute is absent, classify a recognized operation from the span name before consulting inherited operation baggage; retain existing initial-name and instrumentation-scope fallbacks.

**Tech Stack:** Python 3.10+, OpenTelemetry API/SDK, pytest, unittest mocks

## Global Constraints

- Change only GenAI classification precedence and focused regression coverage.
- Preserve explicit operation-attribute precedence.
- Preserve custom baggage propagation to recognized GenAI spans.
- Preserve baggage operation inference for spans whose names do not identify a supported operation.
- Do not change the baggage-builder API, metadata format, or public APIs.

---

### Task 1: Prioritize recognized span operations over inherited baggage

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/_gen_ai_span_classifier.py:91-99`
- Test: `tests/a365/test_span_processor.py`

**Interfaces:**
- Consumes: `_operation_name_from_span_name(span: Any) -> str | None` and `_recognized_operation_name(value: object | None) -> str | None`
- Produces: `_classify_gen_ai_span(...) -> _GenAISpanClassification` with span-name operation precedence over baggage when no explicit operation attribute exists

- [ ] **Step 1: Write the failing regression test**

Add this test near the existing baggage-operation classification tests:

```python
def test_span_name_operation_takes_precedence_over_inherited_baggage_operation(self):
    processor = A365SpanProcessor()
    span = _mock_span("execute_tool get_weather")

    with (
        BaggageBuilder()
        .set_pairs(
            {
                GEN_AI_OPERATION_NAME_KEY: "invoke_agent",
                "microsoft.a365.caller.agent.id": "caller-1",
                "server.address": "agent.contoso.com",
            }
        )
        .custom_attribute("customer.tier", "gold")
        .build()
    ):
        processor.on_start(span, parent_context=context.get_current())

    span.set_attribute.assert_any_call("customer.tier", "gold")
    for call in span.set_attribute.call_args_list:
        self.assertNotIn(call[0][0], ("microsoft.a365.caller.agent.id", "server.address"))
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run:

```powershell
python -m pytest tests\a365\test_span_processor.py::TestA365SpanProcessor::test_span_name_operation_takes_precedence_over_inherited_baggage_operation -v
```

Expected: FAIL because `microsoft.a365.caller.agent.id` or `server.address` is copied after inherited `invoke_agent` baggage wins classification.

- [ ] **Step 3: Implement the precedence change**

Replace the non-explicit classification block with:

```python
operation_name = _operation_name_from_span_name(span)
if operation_name is None:
    operation_name = _recognized_operation_name(baggage_map.get(GEN_AI_OPERATION_NAME_KEY))
if operation_name is not None:
    return _GenAISpanClassification(True, operation_name)
```

Update the classifier docstring to state that, when there is no explicit operation attribute, recognized span names take precedence over baggage operation inference.

- [ ] **Step 4: Run focused processor and classifier tests**

Run:

```powershell
python -m pytest tests\a365\test_span_processor.py tests\a365\test_gen_ai_span_classifier.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 5: Run formatting and diff validation**

Run:

```powershell
python -m black --check src\microsoft\opentelemetry\a365\core\exporters\_gen_ai_span_classifier.py tests\a365\test_span_processor.py
git diff --check
```

Expected: both commands exit successfully with no formatting or whitespace errors.

- [ ] **Step 6: Commit the fix**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\_gen_ai_span_classifier.py tests\a365\test_span_processor.py docs\superpowers\plans\2026-09-22-genai-operation-precedence.md
git commit -m "Fix GenAI operation classification precedence" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
