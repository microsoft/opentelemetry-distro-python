---
name: otel-distro
description: Integrate Microsoft OpenTelemetry Distro into a Python AI agent project — unified observability with Agent 365, Azure Monitor, and OTLP export
user-invocable: true
---

You are integrating the Microsoft OpenTelemetry Distro into the user's existing Python AI agent project. This is the new unified distro that replaces the old fragmented `microsoft-agents-a365-observability-*` packages with a single `microsoft-opentelemetry` package.

The user may optionally provide arguments specifying their AI framework, whether they use Bot Framework hosting, or other constraints. If not provided, you will discover these by reading their code.

## Phase 1 — Analyze the project

Before writing any code, read the project to answer these questions:

1. **Which AI framework does it use?** Look for: OpenAI Agents SDK (`openai`/`agents`), Semantic Kernel (`semantic_kernel`), Microsoft Agent Framework (`microsoft_agents`), LangChain (`langchain`), or none/custom.
2. **Does the project use Bot Framework hosting?** Search for imports from `microsoft_agents.hosting` or `microsoft-agents-hosting-core` in requirements/pyproject.toml. This determines the hosting vs standalone path.
3. **Where is the agent entry point?** Find the function or method that handles incoming messages (the request handler).
4. **Where is app startup?** Find where the application initializes (e.g., `app.py`, `main.py`).
5. **What is the agent's identity?** Look for existing agent_id, tenant_id, blueprint_id values in config, env vars, or code.
6. **Is there an existing requirements file?** Check for `requirements.txt`, `pyproject.toml`, or similar.
7. **Is the project already using old A365 SDK packages?** Check for `microsoft-agents-a365-observability-*` imports. If so, this is a migration — follow the migration notes in Phase 3.

State your findings to the user in 3-4 sentences, then proceed.

## Phase 2 — Choose integration path

Follow this decision tree exactly:

```
Uses Bot Framework hosting (microsoft-agents-hosting-core)?
├─ YES → HOSTED PATH: BaggageMiddleware + AgenticTokenCache
│    Framework?
│    ├─ OpenAI Agents SDK → auto-instrument via instrumentation_options
│    ├─ Semantic Kernel   → auto-instrument via instrumentation_options
│    ├─ Agent Framework   → auto-instrument via instrumentation_options
│    ├─ LangChain         → auto-instrument via instrumentation_options
│    └─ Other/custom      → manual instrumentation (scope classes)
│
└─ NO → STANDALONE PATH: manual BaggageBuilder + token resolver
     Framework?
     ├─ Supported → auto-instrument via instrumentation_options
     └─ Other     → manual instrumentation (scope classes)
```

## Phase 3 — Implement

### INVARIANT RULES — Violating any of these produces a broken integration

1. **Baggage is mandatory.** The exporter partitions spans by `(tenant_id, agent_id)`. Spans missing either value are **silently dropped**. Every code path that creates scopes MUST be inside a `BaggageBuilder` context with both `.tenant_id(...)` and `.agent_id(...)`.
2. **Scope nesting order:** `BaggageBuilder.build()` → `InvokeAgentScope.start()` → `InferenceScope.start()` / `ExecuteToolScope.start()`. Inference and tool scopes are children of the invoke scope.
3. **Four scopes available:** `InvokeAgentScope`, `InferenceScope`, `ExecuteToolScope`, `OutputScope`. The first three are required for M365 store publishing.
4. **`use_microsoft_opentelemetry()` is called once at app startup.** It initializes singleton providers. Never call it per-request.
5. **Token resolver signature:** `(agent_id: str, tenant_id: str) -> str | None`. Must be **synchronous**. Cache tokens from async handlers for the sync resolver.
6. **Both `enable_a365=True` AND the exporter flag are needed.** Set `a365_enable_observability_exporter=True` in code or `ENABLE_A365_OBSERVABILITY_EXPORTER=true` in env. Without both, spans are enriched but not exported to A365.
7. **Auto-instrumentation still requires baggage.** It does NOT set baggage for you.
8. **Do not mix auto and manual instrumentation for the same framework.**
9. **A365-only mode:** When `enable_a365=True` without Azure Monitor, web/HTTP/DB instrumentations are auto-disabled. GenAI instrumentations stay enabled. Override with `instrumentation_options` if needed.

### Step 3.1 — Install package

```bash
pip install microsoft-opentelemetry
```

If migrating from old SDK, remove:
```bash
pip uninstall microsoft-agents-a365-observability-core microsoft-agents-a365-observability-hosting microsoft-agents-a365-observability-extensions-openai microsoft-agents-a365-observability-extensions-semantic-kernel microsoft-agents-a365-observability-extensions-agent-framework microsoft-agents-a365-observability-extensions-langchain microsoft-agents-a365-runtime
```

### Step 3.2 — Add observability configuration to app startup

Use these exact imports. Do not guess module paths.

```python
from microsoft.opentelemetry import use_microsoft_opentelemetry
```

Call once at module level or in the app initialization function:

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    a365_token_resolver=my_token_resolver,
    instrumentation_options={
        "openai_agents": {"enabled": True},   # if using OpenAI Agents SDK
        "semantic_kernel": {"enabled": True},  # if using Semantic Kernel
        "agent_framework": {"enabled": True},  # if using Agent Framework
        "langchain": {"enabled": True},        # if using LangChain
    },
)
```

To also set service identity:

```python
from opentelemetry.sdk.resources import Resource

use_microsoft_opentelemetry(
    enable_a365=True,
    resource=Resource.create({
        "service.name": "<infer from project>",
        "service.namespace": "<infer from project>",
    }),
    a365_token_resolver=my_token_resolver,
)
```

### Step 3.3 — Set up token resolver

**Hosted path** — use `AgenticTokenCache`:
```python
from microsoft.opentelemetry import use_microsoft_opentelemetry
from microsoft.opentelemetry.a365.hosting.token_cache_helpers import AgenticTokenCache, AgenticTokenStruct
from microsoft.opentelemetry.a365.runtime import get_observability_authentication_scope

token_cache = AgenticTokenCache()
_cached_tokens: dict[tuple[str, str], str | None] = {}

def sync_token_resolver(agent_id: str, tenant_id: str) -> str | None:
    return _cached_tokens.get((agent_id, tenant_id))

use_microsoft_opentelemetry(enable_a365=True, a365_token_resolver=sync_token_resolver)

# In the activity handler:
async def on_message(context, _state):
    agent_id = context.activity.recipient.id
    tenant_id = context.activity.recipient.tenant_id
    token_cache.register_observability(
        agent_id=agent_id,
        tenant_id=tenant_id,
        token_generator=AgenticTokenStruct(
            authorization=AGENT_APP.auth,
            turn_context=context,
        ),
        observability_scopes=get_observability_authentication_scope(),
    )
    _cached_tokens[(agent_id, tenant_id)] = await token_cache.get_observability_token(
        agent_id, tenant_id,
    )
```

**Automatic (no resolver)** — the distro tries FIC via `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__*` env vars, then falls back to `DefaultAzureCredential`:
```python
use_microsoft_opentelemetry(enable_a365=True)
```

**Standalone path** — implement a manual resolver with MSAL or `@azure/identity`. The token must have scope `Agent365.Observability.OtelWrite` (resource ID `9b975845-388f-4429-889e-eab1ef63949c`). Leave a TODO comment for the user to fill in auth logic.

### Step 3.4 — Set up baggage

**Hosted path (preferred)** — register middleware:
```python
from microsoft.opentelemetry.a365.hosting import ObservabilityHostingManager, ObservabilityHostingOptions

options = ObservabilityHostingOptions(enable_baggage=True)
ObservabilityHostingManager.configure(adapter.middleware_set, options)
```

**Alternative hosted** — populate from TurnContext manually:
```python
from microsoft.opentelemetry.a365.core import BaggageBuilder
from microsoft.opentelemetry.a365.hosting.scope_helpers.populate_baggage import populate

builder = BaggageBuilder()
populate(builder, turn_context)

with builder.build():
    # All spans created here inherit baggage values
    pass
```

**Standalone path** — manual BaggageBuilder in the request handler:
```python
from microsoft.opentelemetry.a365.core import BaggageBuilder

with (
    BaggageBuilder()
    .tenant_id("<TENANT_ID>")
    .agent_id("<AGENT_ID>")
    .conversation_id("<CONV_ID>")
    .build()
):
    # All spans created here inherit baggage values
    pass
```

### Step 3.5 — Add instrumentation

**Auto-instrumentation** (configured in Step 3.2 via `instrumentation_options`):

| Framework | Key |
|---|---|
| OpenAI Agents SDK | `"openai_agents": {"enabled": True}` |
| Semantic Kernel | `"semantic_kernel": {"enabled": True}` |
| Agent Framework | `"agent_framework": {"enabled": True}` |
| LangChain | `"langchain": {"enabled": True}` |

No separate `.instrument()` calls needed — the distro handles it automatically.

**Manual instrumentation** — wrap existing code with scope context managers. Use these exact imports:

```python
from microsoft.opentelemetry.a365.core import (
    InvokeAgentScope, InvokeAgentScopeDetails,
    InferenceScope, InferenceCallDetails, InferenceOperationType,
    ExecuteToolScope, ToolCallDetails, ToolType,
    OutputScope, Response, SpanDetails,
    AgentDetails, CallerDetails, UserDetails,
    Request, Channel, ServiceEndpoint,
)
```

Nest scopes in this order inside the baggage context:

1. `with InvokeAgentScope.start(request, scope_details, agent_details) as scope:` — wraps the entire request handler. Call `scope.record_input_messages()`, `scope.record_output_messages()` after.
2. `with InferenceScope.start(request, inference_details, agent_details) as scope:` — wraps each LLM call. Call `scope.record_output_messages()`, `scope.record_input_tokens()`, `scope.record_output_tokens()`, `scope.record_finish_reasons()` after.
3. `with ExecuteToolScope.start(request, tool_details, agent_details) as scope:` — wraps each tool call. Call `scope.record_response()` after.
4. `OutputScope.start(request, response, agent_details, span_details=SpanDetails(parent_context=...))` — for async output after invoke scope ends. Capture parent context via `invoke_scope.get_span_context()` before exiting.

### Step 3.6 — Add environment variable

Ensure the project has `ENABLE_A365_OBSERVABILITY_EXPORTER` in its env config (`.env`, environment docs, etc.) set to `false` for development.

## Phase 4 — Verify

After making all changes, run through this checklist mentally and report status to the user:

```
[ ] microsoft-opentelemetry installed (old A365 packages removed if migrating)
[ ] use_microsoft_opentelemetry() called once at startup with enable_a365=True
[ ] Token resolver provided (AgenticTokenCache, manual, or automatic FIC/DAC)
[ ] Baggage context established (middleware or manual BaggageBuilder) with tenant_id AND agent_id
[ ] InvokeAgentScope wraps the agent entry point
[ ] InferenceScope wraps every LLM call (or auto-instrumentation enabled)
[ ] ExecuteToolScope wraps every tool call (or auto-instrumentation enabled)
[ ] ENABLE_A365_OBSERVABILITY_EXPORTER env var documented
[ ] No per-request calls to use_microsoft_opentelemetry()
[ ] Scope nesting order correct: Baggage → InvokeAgent → Inference/Tool
```

Tell the user what to do next:
1. Install: `pip install microsoft-opentelemetry`
2. Set `ENABLE_A365_OBSERVABILITY_EXPORTER=false` and run the agent to see console spans
3. If using the manual token resolver stub, implement the actual token acquisition
4. Set `ENABLE_A365_OBSERVABILITY_EXPORTER=true` and verify at `admin.cloud.microsoft/#/agents/all`

## Troubleshooting reference

| Symptom | Cause | Fix |
|---|---|---|
| No spans in admin center | Exporter not enabled | Set `ENABLE_A365_OBSERVABILITY_EXPORTER=true` AND `enable_a365=True` in code |
| "No spans with tenant/agent identity" | Missing baggage | Add `tenant_id` AND `agent_id` to BaggageBuilder |
| Export succeeds (HTTP 200) but no data in admin center | Spans accepted but not yet stored, or unsupported operation names | HTTP 200 means accepted, not stored. Verify spans use `invoke_agent`, `execute_tool`, `chat`, or `output_messages` as operation names. Data may take a few minutes to appear. |
| Token resolver returns None | Token not cached from async handler | Ensure the async activity handler caches the token before the sync resolver is called |
| HTTP 401 | Wrong token scope | Verify token has `Agent365.Observability.OtelWrite` scope |
| HTTP 403 | Missing license, permission, or tenant not enabled | Need M365 E7 / Agent 365 Frontier license; grant `Agent365.Observability.OtelWrite` via `a365 setup admin` or Entra portal (resource `9b975845-388f-4429-889e-eab1ef63949c`, both Delegated + Application). If license and permission are correct, contact the Agent 365 team — your tenant may not be enabled yet. |
| HTTP 429 / 5xx | Transient | SDK auto-retries. If persistent, increase `a365_scheduled_delay_ms` |
| Timeout | Network / slow endpoint | Increase `a365_exporter_timeout_ms` |
| Web/HTTP spans missing | A365-only mode auto-disables them | Re-enable via `instrumentation_options={"flask": {"enabled": True}}` |
