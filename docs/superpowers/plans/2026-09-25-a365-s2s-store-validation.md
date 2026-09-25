# A365 S2S Store Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update PR #217 so the A365 S2S sample is current with `main`, demonstrates all public observability scopes, and proves the Microsoft Learn Store-required telemetry attributes are emitted.

**Architecture:** Keep one runnable sample module under `samples/a365/s2s/`, but separate configuration/token acquisition from a deterministic `_emit_sample_telemetry` function that tests can execute without network access. Use the existing A365 scope classes and enriching span processor so the test validates final exported span attributes, including baggage propagation.

**Tech Stack:** Python 3.10+, Microsoft OpenTelemetry distro, OpenTelemetry SDK in-memory exporter, MSAL, pytest, uv, Black, Pylint, Mypy.

## Global Constraints

- Merge `origin/main` into `nikhilc/add-a365-s2s-sample`; do not rebase or rewrite PR history.
- Preserve current `main` dependency metadata and root `uv.lock`; do not restore the obsolete `openai<2.45.0` constraint.
- Remove `samples/a365/s2s/.env.example`, `samples/a365/s2s/pyproject.toml`, and `samples/a365/s2s/uv.lock`.
- Keep the sample under `samples/a365/s2s/`.
- Demonstrate `InvokeAgentScope`, `ApplyGuardrailScope`, `InferenceScope`, `ExecuteToolScope`, and `OutputScope`.
- Validate the Microsoft Learn Store attribute lists for invoke-agent, inference, execute-tool, and output spans.
- Do not require or emit `microsoft.agent.user.id` or `microsoft.agent.user.email` for the S2S flow.
- Require real tenant, agent, blueprint, and human caller identity values through environment variables.
- Preserve tenant mismatch rejection, tenant/agent token caching, and duplicate-handler protection.
- Do not refactor unrelated A365 samples or change scope/exporter APIs.

---

## File Structure

- `samples/a365/s2s/s2s_exporter.py`: S2S environment validation, MSAL token resolver, exporter logging, deterministic sample telemetry, and CLI entry point.
- `samples/a365/s2s/README.md`: prerequisites, environment contract, run command, Store-validation scope/attribute coverage, and troubleshooting.
- `tests/a365/test_s2s_sample.py`: network-free tests for emitted scope coverage, Store-required attributes, S2S exemptions, guardrail events, token tenant validation, cache reuse, and logging idempotence.
- `README.md`: sample catalog link only.
- `docs/superpowers/specs/2026-09-25-a365-s2s-store-validation-design.md`: approved design, retained unchanged.

### Task 1: Merge Current Main and Remove Obsolete PR Artifacts

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Delete: `samples/a365/s2s/.env.example`
- Delete: `samples/a365/s2s/pyproject.toml`
- Delete: `samples/a365/s2s/uv.lock`

**Interfaces:**
- Consumes: `origin/main` at the latest fetched commit and the existing PR branch.
- Produces: A conflict-free branch containing current scope APIs and only the S2S sample changes relevant to PR #217.

- [ ] **Step 1: Fetch and merge current main**

Run:

```powershell
git fetch origin main
git merge --no-ff origin/main
```

Expected: Git reports conflicts in `README.md` and `pyproject.toml`; the merge remains in progress.

- [ ] **Step 2: Resolve dependency metadata in favor of current main**

Run:

```powershell
git checkout --theirs pyproject.toml
git add pyproject.toml
```

Expected: `pyproject.toml` matches `origin/main`; the merge brings in the
current root `uv.lock`; no `openai<2.45.0` lines remain.

- [ ] **Step 3: Resolve the sample catalog from current main**

Run:

```powershell
git checkout --theirs README.md
git add README.md
```

Expected: `README.md` contains the current `main` content. The S2S row will be re-added in Task 4.

- [ ] **Step 4: Remove files rejected in review**

Run:

```powershell
git rm samples\a365\s2s\.env.example samples\a365\s2s\pyproject.toml samples\a365\s2s\uv.lock
git status --short
```

Expected: the three sample-local setup files are staged as deleted and no merge conflict markers remain.

- [ ] **Step 5: Complete the merge commit**

Run:

```powershell
git commit -m "Merge main into A365 S2S sample" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: a merge commit is created and `git status --short` is clean.

### Task 2: Add Failing Store-Contract Span Tests

**Files:**
- Create: `tests/a365/test_s2s_sample.py`
- Test: `tests/a365/test_s2s_sample.py`

**Interfaces:**
- Consumes: Existing `OpenTelemetryScope`, `_EnrichingBatchSpanProcessor`, and A365 semantic constants from current `main`.
- Produces: Test requirements for `s2s_exporter._emit_sample_telemetry(agent_details, user_details, request) -> str`.

- [ ] **Step 1: Create the in-memory span capture fixture**

Create `tests/a365/test_s2s_sample.py` with these imports and fixture:

```python
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from microsoft.opentelemetry.a365.core import AgentDetails, Channel, Request, UserDetails
from microsoft.opentelemetry.a365.core.constants import SOURCE_NAME
from microsoft.opentelemetry.a365.core.exporters.enriching_span_processor import (
    _EnrichingBatchSpanProcessor,
)
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope


SAMPLE_PATH = Path(__file__).parents[2] / "samples" / "a365" / "s2s" / "s2s_exporter.py"
SPEC = importlib.util.spec_from_file_location("a365_s2s_exporter_sample", SAMPLE_PATH)
assert SPEC is not None and SPEC.loader is not None
s2s_exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s2s_exporter)


@pytest.fixture
def captured_spans(monkeypatch):
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    processor = _EnrichingBatchSpanProcessor(
        exporter,
        max_queue_size=64,
        schedule_delay_millis=60_000,
        max_export_batch_size=64,
    )
    provider.add_span_processor(processor)
    OpenTelemetryScope._tracer = provider.get_tracer(SOURCE_NAME)

    yield exporter, provider

    provider.shutdown()
    OpenTelemetryScope._tracer = None
```

- [ ] **Step 2: Define the required Store attributes and sample identities**

Add:

```python
INVOKE_REQUIRED = {
    "microsoft.a365.agent.blueprint.id",
    "gen_ai.agent.id",
    "gen_ai.agent.name",
    "client.address",
    "user.id",
    "user.email",
    "microsoft.channel.name",
    "gen_ai.conversation.id",
    "gen_ai.input.messages",
    "gen_ai.operation.name",
    "gen_ai.output.messages",
    "server.address",
    "server.port",
    "microsoft.tenant.id",
}
INFERENCE_REQUIRED = {
    "microsoft.a365.agent.blueprint.id",
    "gen_ai.agent.id",
    "gen_ai.agent.name",
    "client.address",
    "user.id",
    "user.email",
    "microsoft.channel.name",
    "gen_ai.conversation.id",
    "gen_ai.input.messages",
    "gen_ai.operation.name",
    "gen_ai.output.messages",
    "gen_ai.provider.name",
    "gen_ai.request.model",
    "microsoft.tenant.id",
}
TOOL_REQUIRED = {
    "microsoft.a365.agent.blueprint.id",
    "gen_ai.agent.id",
    "gen_ai.agent.name",
    "client.address",
    "user.id",
    "user.email",
    "microsoft.channel.name",
    "gen_ai.conversation.id",
    "gen_ai.operation.name",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.id",
    "gen_ai.tool.call.result",
    "gen_ai.tool.name",
    "gen_ai.tool.type",
    "microsoft.tenant.id",
}
OUTPUT_REQUIRED = {
    "microsoft.a365.agent.blueprint.id",
    "gen_ai.agent.id",
    "gen_ai.agent.name",
    "client.address",
    "user.id",
    "user.email",
    "microsoft.channel.name",
    "gen_ai.conversation.id",
    "gen_ai.operation.name",
    "gen_ai.output.messages",
    "microsoft.tenant.id",
}


def _sample_inputs():
    agent = AgentDetails(
        agent_id="agent-123",
        agent_name="Weather Agent",
        agent_description="Answers weather questions",
        agent_blueprint_id="blueprint-123",
        tenant_id="tenant-123",
        provider_name="azure-openai",
        agent_version="1.0.0",
    )
    user = UserDetails(
        user_id="user-123",
        user_email="user@contoso.com",
        user_name="Sample User",
        user_client_ip="203.0.113.10",
    )
    request = Request(
        content="What is the weather in Seattle?",
        session_id="session-123",
        channel=Channel(name="service", link="https://contoso.example/channel"),
        conversation_id="conversation-123",
    )
    return agent, user, request
```

- [ ] **Step 3: Write the failing Store-attribute test**

Add:

```python
def test_sample_emits_store_required_attributes(captured_spans):
    exporter, provider = captured_spans
    agent, user, request = _sample_inputs()

    result = s2s_exporter._emit_sample_telemetry(agent, user, request)
    assert result == "It's currently 62°F and partly cloudy in Seattle."
    assert provider.force_flush()

    spans = exporter.get_finished_spans()
    by_operation = {
        span.attributes["gen_ai.operation.name"]: span
        for span in spans
        if "gen_ai.operation.name" in span.attributes
    }
    assert {
        "invoke_agent",
        "apply_guardrail",
        "chat",
        "execute_tool",
        "output_messages",
    }.issubset(by_operation)

    required_by_operation = {
        "invoke_agent": INVOKE_REQUIRED,
        "chat": INFERENCE_REQUIRED,
        "execute_tool": TOOL_REQUIRED,
        "output_messages": OUTPUT_REQUIRED,
    }
    for operation, required in required_by_operation.items():
        attributes = dict(by_operation[operation].attributes)
        assert required <= attributes.keys(), f"{operation} missing {required - attributes.keys()}"
        assert "microsoft.agent.user.id" not in attributes
        assert "microsoft.agent.user.email" not in attributes
```

- [ ] **Step 4: Write the failing guardrail event test**

Add:

```python
def test_sample_emits_guardrail_details_and_finding(captured_spans):
    exporter, provider = captured_spans
    agent, user, request = _sample_inputs()

    s2s_exporter._emit_sample_telemetry(agent, user, request)
    assert provider.force_flush()

    guardrail = next(
        span
        for span in exporter.get_finished_spans()
        if span.attributes.get("gen_ai.operation.name") == "apply_guardrail"
    )
    assert guardrail.attributes["gen_ai.security.target.type"] == "llm_input"
    assert guardrail.attributes["gen_ai.security.decision.type"] == "allow"
    assert guardrail.attributes["gen_ai.guardian.name"] == "Sample Content Safety"
    assert [event.name for event in guardrail.events] == ["microsoft.security.finding"]
```

- [ ] **Step 5: Run tests and verify they fail for the missing helper**

Run:

```powershell
uv run pytest tests\a365\test_s2s_sample.py -q
```

Expected: FAIL because `s2s_exporter.py` does not define `_emit_sample_telemetry` and does not emit guardrail/output scopes.

- [ ] **Step 6: Commit the failing tests**

Run:

```powershell
git add tests\a365\test_s2s_sample.py
git commit -m "test: define A365 S2S store telemetry contract" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one test-only commit.

### Task 3: Implement All Scopes and Required Store Attributes

**Files:**
- Modify: `samples/a365/s2s/s2s_exporter.py`
- Test: `tests/a365/test_s2s_sample.py`

**Interfaces:**
- Consumes: `AgentDetails`, `UserDetails`, and `Request`.
- Produces: `_emit_sample_telemetry(agent_details: AgentDetails, user_details: UserDetails, request: Request) -> str`.

- [ ] **Step 1: Replace dotenv configuration with explicit environment names**

Remove `python-dotenv`, `load_dotenv`, and the `load_dotenv()` call. Add:

```python
A365_AGENT_ID_ENV = "A365_AGENT_ID"
A365_AGENT_BLUEPRINT_ID_ENV = "A365_AGENT_BLUEPRINT_ID"
A365_CALLER_USER_ID_ENV = "A365_CALLER_USER_ID"
A365_CALLER_USER_EMAIL_ENV = "A365_CALLER_USER_EMAIL"
A365_CALLER_CLIENT_IP_ENV = "A365_CALLER_CLIENT_IP"
```

Change `_require_env` to:

```python
def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or (value.startswith("<") and value.endswith(">")):
        raise SystemExit(f"Environment variable {name} is not set. See samples/a365/s2s/README.md.")
    return value
```

- [ ] **Step 2: Import all current scope and model types**

Extend the A365 imports with:

```python
ApplyGuardrailScope,
CallerDetails,
Channel,
GuardrailDecisionType,
GuardrailDetails,
GuardrailFinding,
GuardrailRiskSeverity,
GuardrailTargetType,
OutputScope,
Response,
SpanDetails,
UserDetails,
```

- [ ] **Step 3: Add the deterministic telemetry function**

Add this function before `main()`:

```python
def _emit_sample_telemetry(
    agent_details: AgentDetails,
    user_details: UserDetails,
    request: Request,
) -> str:
    user_question = "What's the weather in Seattle?"
    final_answer = "It's currently 62°F and partly cloudy in Seattle."
    invoke_context = None

    baggage = (
        BaggageBuilder()
        .tenant_id(agent_details.tenant_id)
        .agent_id(agent_details.agent_id)
        .agent_blueprint_id(agent_details.agent_blueprint_id)
        .agent_name(agent_details.agent_name)
        .agent_description(agent_details.agent_description)
        .agent_version(agent_details.agent_version)
        .user_id(user_details.user_id)
        .user_email(user_details.user_email)
        .user_name(user_details.user_name)
        .user_client_ip(user_details.user_client_ip)
        .channel_name(request.channel.name if request.channel else None)
        .channel_links(request.channel.link if request.channel else None)
        .session_id(request.session_id)
        .conversation_id(request.conversation_id)
        .invoke_agent_server("weather-agent.contoso.com", 8443)
    )

    with baggage.build():
        with InvokeAgentScope.start(
            request=request,
            scope_details=InvokeAgentScopeDetails(
                endpoint=ServiceEndpoint(hostname="weather-agent.contoso.com", port=8443),
            ),
            agent_details=agent_details,
            caller_details=CallerDetails(user_details=user_details),
        ) as invoke_scope:
            invoke_scope.record_input_messages(
                InputMessages(
                    messages=[
                        ChatMessage(role=MessageRole.USER, parts=[TextPart(content=user_question)])
                    ]
                )
            )

            with ApplyGuardrailScope.start(
                details=GuardrailDetails(
                    target_type=GuardrailTargetType.LLM_INPUT,
                    decision_type=GuardrailDecisionType.ALLOW,
                    guardian_name="Sample Content Safety",
                    guardian_id="sample-content-safety",
                    guardian_provider_name="contoso.security",
                    guardian_version="1.0",
                    target_id="prompt-123",
                    decision_reason="No unsafe content detected",
                    decision_code="allowed",
                    policy_id="policy-123",
                    policy_name="Default Prompt Safety",
                    policy_version="1.0",
                    content_modified=False,
                ),
                agent_details=agent_details,
                request=request,
                user_details=user_details,
            ) as guardrail_scope:
                guardrail_scope.record_content_input(user_question)
                guardrail_scope.record_finding(
                    GuardrailFinding(
                        risk_category="unsafe_content",
                        risk_severity=GuardrailRiskSeverity.NONE,
                        risk_score=0.0,
                        policy_decision_type=GuardrailDecisionType.ALLOW,
                        policy_id="policy-123",
                        policy_name="Default Prompt Safety",
                        policy_version="1.0",
                    )
                )

            with InferenceScope.start(
                request=request,
                details=InferenceCallDetails(
                    operationName=InferenceOperationType.CHAT,
                    model="gpt-4o",
                    providerName="azure-openai",
                    endpoint=ServiceEndpoint(hostname="example.openai.azure.com", port=443),
                ),
                agent_details=agent_details,
                user_details=user_details,
            ) as inference_scope:
                inference_scope.record_input_messages(
                    InputMessages(
                        messages=[
                            ChatMessage(
                                role=MessageRole.SYSTEM,
                                parts=[TextPart(content="You are a helpful weather assistant.")],
                            ),
                            ChatMessage(role=MessageRole.USER, parts=[TextPart(content=user_question)]),
                        ]
                    )
                )
                inference_scope.record_input_tokens(45)
                inference_scope.record_output_tokens(12)
                inference_scope.record_finish_reasons(["tool_call"])
                inference_scope.record_output_messages(
                    OutputMessages(
                        messages=[
                            OutputMessage(
                                role=MessageRole.ASSISTANT,
                                parts=[TextPart(content="I'll look up the weather for Seattle.")],
                                finish_reason="tool_call",
                            )
                        ]
                    )
                )

            with ExecuteToolScope.start(
                request=request,
                details=ToolCallDetails(
                    tool_name="get_weather",
                    arguments={"city": "Seattle", "units": "fahrenheit"},
                    tool_call_id="call-123",
                    description="Fetches current weather for a city",
                    tool_type=ToolType.FUNCTION.value,
                    endpoint=ServiceEndpoint(hostname="weather-api.contoso.com", port=443),
                ),
                agent_details=agent_details,
                user_details=user_details,
            ) as tool_scope:
                tool_scope.record_response('{"temperature":62,"condition":"Partly cloudy"}')

            invoke_scope.record_output_messages(
                OutputMessages(
                    messages=[
                        OutputMessage(
                            role=MessageRole.ASSISTANT,
                            parts=[TextPart(content=final_answer)],
                            finish_reason="stop",
                        )
                    ]
                )
            )
            invoke_context = invoke_scope.get_context()

        assert invoke_context is not None
        with OutputScope.start(
            request=request,
            response=Response(messages=final_answer),
            agent_details=agent_details,
            user_details=user_details,
            span_details=SpanDetails(parent_context=invoke_context),
        ):
            pass

    return final_answer
```

- [ ] **Step 4: Build real identities in `main()`**

Replace the old optional agent-ID fallback and inline scope body with:

```python
tenant_id = _require_env(A365_SERVICE_TENANT_ID_ENV)
agent = AgentDetails(
    agent_id=_require_env(A365_AGENT_ID_ENV),
    agent_name="Weather Agent",
    agent_description="Answers weather-related questions",
    agent_blueprint_id=_require_env(A365_AGENT_BLUEPRINT_ID_ENV),
    tenant_id=tenant_id,
    provider_name="azure-openai",
    agent_version="1.0.0",
)
user = UserDetails(
    user_id=_require_env(A365_CALLER_USER_ID_ENV),
    user_email=_require_env(A365_CALLER_USER_EMAIL_ENV),
    user_name="Sample Caller",
    user_client_ip=_require_env(A365_CALLER_CLIENT_IP_ENV),
)
request = Request(
    content="What's the weather in Seattle?",
    session_id="session-s2s-123",
    channel=Channel(name="service", link="https://contoso.example/a365-s2s"),
    conversation_id="conv-s2s-789",
)
_emit_sample_telemetry(agent, user, request)
```

Do not set `agentic_user_id` or `agentic_user_email`.

- [ ] **Step 5: Run the Store-contract tests**

Run:

```powershell
uv run pytest tests\a365\test_s2s_sample.py -q
```

Expected: both span tests PASS. If the operation value for inference is normalized differently, inspect the emitted `gen_ai.operation.name` and update the test to the repository's actual semantic value rather than weakening the assertion.

- [ ] **Step 6: Commit all-scope telemetry**

Run:

```powershell
git add samples\a365\s2s\s2s_exporter.py tests\a365\test_s2s_sample.py
git commit -m "Add store-ready telemetry to A365 S2S sample" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: implementation and passing Store-contract tests are committed together.

### Task 4: Test Token Resolver and Logging Review Fixes

**Files:**
- Modify: `tests/a365/test_s2s_sample.py`
- Test: `tests/a365/test_s2s_sample.py`

**Interfaces:**
- Consumes: `build_s2s_token_resolver() -> Callable[[str, str], str | None]` and `_configure_export_logging() -> None`.
- Produces: Regression coverage for previously addressed PR comments.

- [ ] **Step 1: Add an environment helper**

Add:

```python
S2S_ENV = {
    s2s_exporter.A365_SERVICE_CLIENT_ID_ENV: "blueprint-client-id",
    s2s_exporter.A365_SERVICE_CLIENT_SECRET_ENV: "secret",
    s2s_exporter.A365_SERVICE_TENANT_ID_ENV: "tenant-123",
    s2s_exporter.A365_AGENT_APP_INSTANCE_ID_ENV: "instance-123",
}
```

- [ ] **Step 2: Test tenant mismatch fails before MSAL acquisition**

Add:

```python
def test_token_resolver_rejects_tenant_mismatch(monkeypatch, capsys):
    fake_msal = MagicMock()
    monkeypatch.setitem(sys.modules, "msal", fake_msal)
    for name, value in S2S_ENV.items():
        monkeypatch.setenv(name, value)

    resolver = s2s_exporter.build_s2s_token_resolver()

    assert resolver("agent-123", "different-tenant") is None
    assert "does not match configured tenant" in capsys.readouterr().out
    fake_msal.ConfidentialClientApplication.assert_not_called()
```

- [ ] **Step 3: Test successful token reuse**

Add:

```python
def test_token_resolver_caches_by_tenant_and_agent(monkeypatch):
    first_app = MagicMock()
    first_app.acquire_token_for_client.return_value = {"access_token": "agent-token"}
    second_app = MagicMock()
    second_app.acquire_token_for_client.return_value = {
        "access_token": "observability-token",
        "expires_in": 3600,
    }
    fake_msal = MagicMock()
    fake_msal.ConfidentialClientApplication.side_effect = [first_app, second_app]
    monkeypatch.setitem(sys.modules, "msal", fake_msal)
    for name, value in S2S_ENV.items():
        monkeypatch.setenv(name, value)

    resolver = s2s_exporter.build_s2s_token_resolver()

    assert resolver("agent-123", "tenant-123") == "observability-token"
    assert resolver("agent-123", "tenant-123") == "observability-token"
    assert fake_msal.ConfidentialClientApplication.call_count == 2
```

- [ ] **Step 4: Test exporter logging is idempotent**

Add:

```python
def test_configure_export_logging_adds_one_named_handler():
    logger = s2s_exporter.logging.getLogger(
        "microsoft.opentelemetry.a365.core.exporters.agent365_exporter"
    )
    original_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    try:
        logger.handlers = []
        s2s_exporter._configure_export_logging()
        s2s_exporter._configure_export_logging()

        matching = [
            handler
            for handler in logger.handlers
            if handler.name == "a365-s2s-sample-export-logging"
        ]
        assert len(matching) == 1
        assert logger.propagate is False
    finally:
        logger.handlers = original_handlers
        logger.propagate = original_propagate
```

- [ ] **Step 5: Run the regression tests**

Run:

```powershell
uv run pytest tests\a365\test_s2s_sample.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit review-fix coverage**

Run:

```powershell
git add tests\a365\test_s2s_sample.py
git commit -m "Test A365 S2S resolver review fixes" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one focused test commit.

### Task 5: Document Setup and Store Validation

**Files:**
- Modify: `samples/a365/s2s/README.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: The final environment constants and run path from `s2s_exporter.py`.
- Produces: Copy-pasteable PowerShell/Bash setup instructions without sample-local project files.

- [ ] **Step 1: Replace sample-local setup instructions**

Document these commands:

```powershell
$env:ENABLE_OBSERVABILITY = "true"
$env:ENABLE_A365_OBSERVABILITY_EXPORTER = "true"
$env:CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID = "<blueprint-app-client-id>"
$env:CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET = "<blueprint-app-secret>"
$env:CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID = "<tenant-guid>"
$env:A365_AGENT_APP_INSTANCE_ID = "<agent-app-instance-id>"
$env:A365_AGENT_ID = "<published-agent-id>"
$env:A365_AGENT_BLUEPRINT_ID = "<agent-blueprint-id>"
$env:A365_CALLER_USER_ID = "<caller-user-id>"
$env:A365_CALLER_USER_EMAIL = "<caller-user-email>"
$env:A365_CALLER_CLIENT_IP = "<caller-client-ip>"

uv run --with msal python samples\a365\s2s\s2s_exporter.py
```

Also provide equivalent Bash `export NAME=value` syntax. State that the values must be real deployment values and that angle-bracket placeholders are rejected.

- [ ] **Step 2: Document scope and Store coverage**

Add a table:

```markdown
| Scope | Sample behavior | Store validation |
| --- | --- | --- |
| `InvokeAgentScope` | Root request, identity, endpoint, input, final output | Required |
| `InferenceScope` | Model/provider, messages, token usage, finish reason | Required |
| `ExecuteToolScope` | Tool identity, arguments, result | Required |
| `OutputScope` | Child span for asynchronous/final output | Validate before publishing |
| `ApplyGuardrailScope` | Input safety decision and finding event | Additional security telemetry |
```

Explicitly state that S2S does not populate `microsoft.agent.user.id` or `microsoft.agent.user.email`.

- [ ] **Step 3: Preserve permission and diagnostics guidance**

Keep:

- `Agent365.Observability.OtelWrite` application permission with admin consent.
- `a365_use_s2s_endpoint=True`.
- Expected HTTP success/correlation-ID logging.
- HTTP 401/403 troubleshooting.
- Link to the Microsoft Learn Store-validation section.

- [ ] **Step 4: Re-add the root sample catalog row**

Under the A365 sample rows in `README.md`, add:

```markdown
| [samples/a365/s2s/s2s_exporter.py](https://github.com/microsoft/opentelemetry-distro-python/blob/main/samples/a365/s2s/s2s_exporter.py) | A365 | Store-ready S2S export with all manual observability scopes |
```

- [ ] **Step 5: Commit documentation**

Run:

```powershell
git add README.md samples\a365\s2s\README.md
git commit -m "Document A365 S2S store validation setup" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: sample setup no longer references `.env.example`, a local `pyproject.toml`, or local `uv.lock`.

### Task 6: Run Final Validation and Update the PR

**Files:**
- Verify: `samples/a365/s2s/s2s_exporter.py`
- Verify: `samples/a365/s2s/README.md`
- Verify: `tests/a365/test_s2s_sample.py`
- Verify: `README.md`

**Interfaces:**
- Consumes: Completed branch.
- Produces: A pushed PR branch with resolved review feedback and passing checks.

- [ ] **Step 1: Format the changed Python files**

Run:

```powershell
uv run black --check samples\a365\s2s\s2s_exporter.py tests\a365\test_s2s_sample.py
```

Expected: `2 files would be left unchanged`.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
uv run pytest tests\a365\test_s2s_sample.py tests\a365\test_apply_guardrail_scope.py tests\a365\test_invoke_agent_scope.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 3: Run targeted static analysis**

Run:

```powershell
uv run pylint samples\a365\s2s\s2s_exporter.py tests\a365\test_s2s_sample.py
uv run mypy samples\a365\s2s\s2s_exporter.py
```

Expected: Pylint exits 0 and Mypy reports `Success: no issues found`.

- [ ] **Step 4: Verify review cleanup and diff scope**

Run:

```powershell
git status --short
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
rg -n "dotenv|\.env\.example|samples/a365/s2s/pyproject|openai<2\.45" README.md pyproject.toml samples\a365\s2s tests\a365\test_s2s_sample.py
```

Expected:

- Working tree clean.
- `git diff --check` prints nothing.
- The rejected sample-local files are absent.
- No obsolete OpenAI cap or dotenv setup remains.

- [ ] **Step 5: Push the PR branch**

Run:

```powershell
git push fork nikhilc/add-a365-s2s-sample
```

Expected: the branch updates successfully and PR #217 is no longer behind `main`.

- [ ] **Step 6: Reply to review threads**

Use `gh api` to reply to the outstanding review thread that requested removal of `.env.example`, sample `pyproject.toml`, and `uv.lock`, stating that the files were removed and prerequisites moved to the README. Do not resolve threads owned by another reviewer unless the API permits the PR author to do so.

- [ ] **Step 7: Verify PR checks start**

Run:

```powershell
gh pr checks 217 --repo microsoft/opentelemetry-distro-python
```

Expected: checks are queued/in progress or passing on the newly pushed head.
