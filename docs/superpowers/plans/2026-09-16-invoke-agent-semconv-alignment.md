# InvokeAgent Semantic Convention Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the new `InvokeAgentScope` cache-token and system-instruction telemetry conform to the current OpenTelemetry GenAI semantic conventions.

**Architecture:** Rename the unreleased cache-creation API and attribute to the canonical cache-write terminology. Represent system instructions as a sequence of existing `TextPart` objects and serialize that sequence through a focused helper that shares the current message serialization primitives.

**Tech Stack:** Python 3.10+, dataclasses, OpenTelemetry Python SDK, pytest, Black, Pylint, Mypy, tox.

## Global Constraints

- Emit cache-write tokens as `gen_ai.usage.cache_write.input_tokens`.
- Expose the response field as `cache_write_input_tokens`; do not retain the unreleased `cache_creation_input_tokens` alias.
- Accept structured system instructions only as `Sequence[TextPart] | None`.
- Emit `gen_ai.system_instructions` as a JSON-encoded array of objects with automatic `"type": "text"` discriminators.
- Preserve non-throwing telemetry serialization behavior.
- Do not modify provider-specific extraction fields such as Anthropic's `cache_creation_input_tokens` outside the new `InvokeAgentScope` API.

---

### Task 1: Rename InvokeAgent cache creation to cache write

**Files:**
- Modify: `tests/a365/test_invoke_agent_scope.py:87-128`
- Modify: `src/microsoft/opentelemetry/a365/core/gen_ai_response_parameters.py:9-18`
- Modify: `src/microsoft/opentelemetry/a365/core/constants.py:56-62`
- Modify: `src/microsoft/opentelemetry/a365/constants.py:59-65`
- Modify: `src/microsoft/opentelemetry/a365/core/invoke_agent_scope.py:35-41,254-268`

**Interfaces:**
- Consumes: `GenAiResponseParameters` passed to `InvokeAgentScope.record_response_parameters`.
- Produces: `cache_write_input_tokens: int | None` and `GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS_KEY = "gen_ai.usage.cache_write.input_tokens"`.

- [ ] **Step 1: Update the focused tests to require cache-write naming**

Replace the cache assertions and constructor argument in
`tests/a365/test_invoke_agent_scope.py`:

```python
scope.record_response_parameters(
    GenAiResponseParameters(
        finish_reasons=["stop"],
        input_tokens=10,
        output_tokens=4,
        cache_write_input_tokens=2,
        cache_read_input_tokens=1,
    )
)
attrs = dict(scope._span.attributes)
assert attrs["gen_ai.response.finish_reasons"] == ("stop",)
assert attrs["gen_ai.usage.input_tokens"] == 10
assert attrs["gen_ai.usage.output_tokens"] == 4
assert attrs["gen_ai.usage.cache_write.input_tokens"] == 2
assert "gen_ai.usage.cache_creation.input_tokens" not in attrs
assert attrs["gen_ai.usage.cache_read.input_tokens"] == 1
```

Update the omission assertions:

```python
assert "gen_ai.usage.cache_write.input_tokens" not in attrs
assert "gen_ai.usage.cache_creation.input_tokens" not in attrs
```

- [ ] **Step 2: Run the cache tests and verify they fail**

Run:

```powershell
python -m pytest tests\a365\test_invoke_agent_scope.py -q
```

Expected: failure because `GenAiResponseParameters` does not accept
`cache_write_input_tokens`.

- [ ] **Step 3: Rename the response model field and constants**

In `src/microsoft/opentelemetry/a365/core/gen_ai_response_parameters.py`:

```python
@dataclass
class GenAiResponseParameters:
    """Optional GenAI response parameters recorded on InvokeAgent spans."""

    finish_reasons: Sequence[str] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
```

In both constants modules, replace the cache-creation declaration with:

```python
GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS_KEY = "gen_ai.usage.cache_write.input_tokens"
```

In `src/microsoft/opentelemetry/a365/core/invoke_agent_scope.py`, import the
new constant and emit the renamed field:

```python
self.set_tag_maybe(
    GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS_KEY,
    parameters.cache_write_input_tokens,
)
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest tests\a365\test_invoke_agent_scope.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 5: Confirm no new InvokeAgent cache-creation symbols remain**

Run:

```powershell
rg "GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY|cache_creation_input_tokens|gen_ai\.usage\.cache_creation\.input_tokens" src\microsoft\opentelemetry\a365 tests\a365\test_invoke_agent_scope.py
```

Expected: no matches. Provider-specific matches elsewhere in `_genai` are
intentionally outside scope.

- [ ] **Step 6: Commit the cache rename**

```powershell
git add src\microsoft\opentelemetry\a365\constants.py src\microsoft\opentelemetry\a365\core\constants.py src\microsoft\opentelemetry\a365\core\gen_ai_response_parameters.py src\microsoft\opentelemetry\a365\core\invoke_agent_scope.py tests\a365\test_invoke_agent_scope.py
git commit -m "fix: use OTel cache-write token attribute" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Serialize structured system instructions

**Files:**
- Modify: `tests/a365/test_invoke_agent_scope.py:5-85,109-128`
- Modify: `src/microsoft/opentelemetry/a365/core/gen_ai_request_parameters.py:5-25`
- Modify: `src/microsoft/opentelemetry/a365/core/message_utils.py:10-119`
- Modify: `src/microsoft/opentelemetry/a365/core/invoke_agent_scope.py:45-55,238-253`

**Interfaces:**
- Consumes: `TextPart` from `microsoft.opentelemetry.a365.core.models.messages`.
- Produces: `GenAiRequestParameters.system_instructions: Sequence[TextPart] | None`.
- Produces: `serialize_system_instructions(parts: Sequence[TextPart]) -> str`.

- [ ] **Step 1: Add tests for the required OTel JSON shape**

Add `json` and `TextPart` imports in `tests/a365/test_invoke_agent_scope.py`:

```python
import json

from microsoft.opentelemetry.a365.core import (
    AgentDetails,
    GenAiRequestParameters,
    GenAiResponseParameters,
    InvokeAgentScope,
    InvokeAgentScopeDetails,
    Request,
    TextPart,
)
```

Change the request parameters in
`test_invoke_agent_scope_records_request_parameters`:

```python
system_instructions=[
    TextPart(content="Be concise."),
    TextPart(content="Return JSON."),
],
```

Replace the system-instruction assertion with:

```python
assert json.loads(attrs["gen_ai.system_instructions"]) == [
    {"content": "Be concise.", "type": "text"},
    {"content": "Return JSON.", "type": "text"},
]
```

Add an omission assertion to
`test_invoke_agent_scope_omits_none_semantic_parameters`:

```python
assert "gen_ai.system_instructions" not in attrs
```

Add a serializer failure test:

```python
def test_invoke_agent_scope_system_instructions_serialization_is_non_throwing():
    parameters = GenAiRequestParameters(
        system_instructions=[object()],  # type: ignore[list-item]
    )

    scope = _start_invoke_agent_scope(InvokeAgentScopeDetails(request_parameters=parameters))
    try:
        attrs = dict(scope._span.attributes)
        assert json.loads(attrs["gen_ai.system_instructions"]) == [
            {
                "content": "[serialization failed: 1 instruction part]",
                "type": "text",
            }
        ]
    finally:
        scope.dispose()
```

- [ ] **Step 2: Run the structured-instruction tests and verify they fail**

Run:

```powershell
python -m pytest tests\a365\test_invoke_agent_scope.py -q
```

Expected: the JSON-shape assertion fails because the span currently contains a
raw sequence unsupported by OpenTelemetry attributes.

- [ ] **Step 3: Type the field as structured instruction parts**

In `src/microsoft/opentelemetry/a365/core/gen_ai_request_parameters.py`:

```python
from typing import Sequence

from microsoft.opentelemetry.a365.core.models.messages import TextPart


@dataclass
class GenAiRequestParameters:
    """Optional GenAI request parameters recorded on InvokeAgent spans."""

    # Existing fields remain unchanged.
    system_instructions: Sequence[TextPart] | None = None
```

- [ ] **Step 4: Extract shared dataclass JSON serialization**

In `src/microsoft/opentelemetry/a365/core/message_utils.py`, import `Sequence`,
then add:

```python
def _serialize_dataclasses(items: Sequence[object]) -> str:
    """Serialize dataclass instances as a JSON array."""
    return json.dumps(
        [asdict(item, dict_factory=_message_dict_factory) for item in items],
        default=str,
        ensure_ascii=False,
    )
```

Use it in `serialize_messages`:

```python
try:
    return _serialize_dataclasses(wrapper.messages)
except Exception:
    logger.warning("Failed to serialize messages; using fallback.", exc_info=True)
    # Preserve the existing fallback construction.
```

Add the structured-instruction serializer:

```python
def serialize_system_instructions(parts: Sequence[TextPart]) -> str:
    """Serialize OTel system-instruction parts as a JSON array."""
    try:
        return _serialize_dataclasses(parts)
    except Exception:
        logger.warning("Failed to serialize system instructions; using fallback.", exc_info=True)
        count = len(parts)
        noun = "instruction part" if count == 1 else "instruction parts"
        return _serialize_dataclasses(
            [TextPart(content=f"[serialization failed: {count} {noun}]")]
        )
```

- [ ] **Step 5: Emit serialized instructions from InvokeAgentScope**

Import `serialize_system_instructions` in
`src/microsoft/opentelemetry/a365/core/invoke_agent_scope.py`, then replace the
raw assignment:

```python
if parameters.system_instructions is not None:
    self.set_tag_maybe(
        GEN_AI_SYSTEM_INSTRUCTIONS_KEY,
        serialize_system_instructions(parameters.system_instructions),
    )
```

- [ ] **Step 6: Run focused tests and verify they pass**

Run:

```powershell
python -m pytest tests\a365\test_invoke_agent_scope.py -q
```

Expected: all tests pass, including structured JSON and non-throwing fallback.

- [ ] **Step 7: Run static checks for the changed Python surface**

Run:

```powershell
python -m black --check src\microsoft\opentelemetry\a365\core\gen_ai_request_parameters.py src\microsoft\opentelemetry\a365\core\gen_ai_response_parameters.py src\microsoft\opentelemetry\a365\core\message_utils.py src\microsoft\opentelemetry\a365\core\invoke_agent_scope.py tests\a365\test_invoke_agent_scope.py
python -m pylint src\microsoft\opentelemetry\a365\core\gen_ai_request_parameters.py src\microsoft\opentelemetry\a365\core\gen_ai_response_parameters.py src\microsoft\opentelemetry\a365\core\message_utils.py src\microsoft\opentelemetry\a365\core\invoke_agent_scope.py tests\a365\test_invoke_agent_scope.py
python -m mypy --python-version 3.10 --show-error-codes --ignore-missing-imports src\microsoft\opentelemetry\a365\core tests\a365\test_invoke_agent_scope.py
```

Expected: each command exits successfully with no errors.

- [ ] **Step 8: Commit structured instruction support**

```powershell
git add src\microsoft\opentelemetry\a365\core\gen_ai_request_parameters.py src\microsoft\opentelemetry\a365\core\message_utils.py src\microsoft\opentelemetry\a365\core\invoke_agent_scope.py tests\a365\test_invoke_agent_scope.py
git commit -m "fix: serialize structured system instructions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Update documentation and close review threads

**Files:**
- Modify: `README.md:127-153`
- Modify: `A365_DOCUMENTATION.md:353-404`
- Modify: `CHANGELOG.md:1-5`

**Interfaces:**
- Consumes: `TextPart`, `cache_write_input_tokens`, and the canonical emitted attribute names from Tasks 1 and 2.
- Produces: Copyable documentation matching the final public API.

- [ ] **Step 1: Update the top-level README example**

Add `TextPart` to the import list and demonstrate structured instructions:

```python
from microsoft.opentelemetry.a365.core import (
    AgentDetails,
    GenAiRequestParameters,
    GenAiResponseParameters,
    InvokeAgentScope,
    InvokeAgentScopeDetails,
    Request,
    TextPart,
)

details = InvokeAgentScopeDetails(
    request_parameters=GenAiRequestParameters(
        model="gpt-4o",
        max_tokens=256,
        stop_sequences=["END"],
        system_instructions=[TextPart(content="Be concise.")],
    )
)
```

Include cache-write usage in the response call:

```python
scope.record_response_parameters(
    GenAiResponseParameters(
        finish_reasons=["stop"],
        output_tokens=18,
        cache_write_input_tokens=4,
    )
)
```

- [ ] **Step 2: Update the A365 guide**

Add `TextPart` to the `InvokeAgentScope` import list, add:

```python
system_instructions=[TextPart(content="Be concise.")],
```

to `GenAiRequestParameters`, and add:

```python
cache_write_input_tokens=4,
```

to the response example. Replace
`gen_ai.usage.cache_creation.input_tokens` with
`gen_ai.usage.cache_write.input_tokens` in the supported attribute list.

- [ ] **Step 3: Clarify the unreleased changelog entry**

Replace the current feature line with:

```markdown
- Add Python-native `InvokeAgentScope` request and response parameter models
  that emit OpenTelemetry GenAI semantic attributes, including structured
  system instructions and cache read/write token counts, introduced by .NET
  PR #120.
```

- [ ] **Step 4: Validate documentation and the complete focused change**

Run:

```powershell
python -m pytest tests\a365\test_invoke_agent_scope.py -q
git diff --check
rg "gen_ai\.usage\.cache_creation\.input_tokens|cache_creation_input_tokens" README.md A365_DOCUMENTATION.md CHANGELOG.md src\microsoft\opentelemetry\a365 tests\a365\test_invoke_agent_scope.py
```

Expected: tests pass, `git diff --check` exits successfully, and `rg` returns no
matches in the scoped InvokeAgent surfaces.

- [ ] **Step 5: Commit documentation alignment**

```powershell
git add README.md A365_DOCUMENTATION.md CHANGELOG.md
git commit -m "docs: align InvokeAgent semantic parameters" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 6: Run repository-standard final validation**

Run:

```powershell
tox -e black
tox -e pylint
tox -e mypy
tox -e pytest-py310 -- tests\a365\test_invoke_agent_scope.py
tox -e docs
git diff --check origin/main...HEAD
```

Expected: every tox environment exits successfully and the diff check reports
no whitespace errors.

- [ ] **Step 7: Push the branch**

```powershell
git push https://github.com/nikhilNava/opentelemetry-distro-python.git HEAD:copilot/invoke-agent-semantic-fields
```

- [ ] **Step 8: Reply to and resolve both GitHub review threads**

Use the REST replies endpoint:

```powershell
$commit = git rev-parse --short HEAD
$cacheReply = "Fixed in $commit. Renamed the new model field, constants, emitted attribute, tests, and docs to the current OTel gen_ai.usage.cache_write.input_tokens convention."
$instructionsReply = "Fixed in $commit. system_instructions now accepts structured TextPart sequences and emits the OTel JSON-array shape through the shared serialization path."
gh api --method POST repos/microsoft/opentelemetry-distro-python/pulls/263/comments/4019541268/replies -f body=$cacheReply
gh api --method POST repos/microsoft/opentelemetry-distro-python/pulls/263/comments/4019544444/replies -f body=$instructionsReply
```

Query the PR review threads with GraphQL, resolve the two matching thread IDs
using `resolveReviewThread`, then query again and confirm both report
`isResolved: true`.
