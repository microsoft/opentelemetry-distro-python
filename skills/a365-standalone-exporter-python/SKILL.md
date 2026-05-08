---
name: a365-standalone-exporter-python
description: Add the A365 standalone SpanExporter to a Python project that already has OpenTelemetry configured — no full distro required, just plug-in export to Agent 365
---

You are adding the `a365-otel-exporter` standalone SpanExporter package to the user's existing Python project. This is the **lightweight** path for teams that already have OpenTelemetry tracing set up and want to add Agent 365 as an additional export destination — without adopting the full `microsoft-opentelemetry` distro.

## When to use this vs the full distro

| Use standalone exporter (`a365-otel-exporter`) | Use full distro (`microsoft-opentelemetry`) |
|---|---|
| Already have a TracerProvider configured | Starting from scratch or want turnkey setup |
| Only need A365 export — keep your existing backends | Want auto-instrumentation for OpenAI/SK/LangChain |
| Minimal dependency footprint | Want BotFramework hosting integration |
| Want full control over span creation | Want scope classes (InvokeAgentScope, etc.) |

## Phase 1 — Analyze the project

Before writing any code, answer:

1. **Does the project already have a TracerProvider?** Look for `TracerProvider()`, `set_tracer_provider()`, or framework-specific OTel setup.
2. **What span processors are configured?** Look for `BatchSpanProcessor` or `SimpleSpanProcessor`.
3. **Where are spans created?** Find the tracer and `start_as_current_span` calls.
4. **What auth mechanism is available?** Managed identity, client credentials, or something else.
5. **Where does the agent get its identity?** Find tenant_id, agent_id in config/env.

State findings in 2-3 sentences, then proceed.

## Phase 2 — Implement

### INVARIANT RULES

1. **Baggage is mandatory.** The exporter groups spans by `(tenant_id, agent_id)`. Spans missing either value are **silently skipped** — no error, no warning in production. Every span MUST carry these attributes.
2. **Token resolver must be synchronous.** Signature: `(agent_id: str, tenant_id: str) -> Optional[str]`. If you need async token acquisition, cache the token and return from cache.
3. **`gen_ai.operation.name` must be set on every span.** Only spans with one of `invoke_agent`, `execute_tool`, `chat`, `output_messages` are processed by A365. All others are silently dropped on the server side.
4. **All attribute values should be strings for A365 processing.** The exporter transmits native types, but A365 only reads `stringValue`. Token counts must be `"42"` not `42`; ports must be `"443"` not `443`.
5. **Do NOT add `?api-version=1`** — the standalone exporter handles this internally.
6. **Add as an additional processor** — do not replace existing exporters.

### Step 2.1 — Install

```bash
pip install a365-otel-exporter

# For Azure Identity token resolution (recommended for Azure-hosted):
pip install a365-otel-exporter[azure]

# For MSAL confidential-client (S2S):
pip install a365-otel-exporter[msal]
```

Dependencies: `opentelemetry-sdk>=1.20.0`, `opentelemetry-api>=1.20.0`, `requests>=2.28.0`.

### Step 2.2 — Create the exporter and add to TracerProvider

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from a365_otel_exporter import A365SpanExporter, A365ExporterOptions

exporter = A365SpanExporter(
    A365ExporterOptions(
        token_resolver=my_token_resolver,
        # endpoint defaults to "https://agent365.svc.cloud.microsoft"
        # timeout_seconds defaults to 30
    )
)

# Add alongside existing exporters — do NOT replace them
provider.add_span_processor(BatchSpanProcessor(exporter))
```

### Step 2.3 — Set up token resolver

Pick one:

**Azure Identity (recommended for Azure-hosted workloads):**

```python
from a365_otel_exporter.auth import create_azure_identity_resolver

resolver = create_azure_identity_resolver()
# Uses DefaultAzureCredential — works with managed identity, CLI, env vars
```

**MSAL Confidential Client (S2S / client credentials):**

```python
from a365_otel_exporter.auth import create_msal_resolver

resolver = create_msal_resolver(
    client_id="<YOUR_APP_CLIENT_ID>",
    client_secret="<YOUR_CLIENT_SECRET>",
    tenant_id="<YOUR_AAD_TENANT_ID>",
)
```

**Custom resolver:**

```python
def my_resolver(agent_id: str, tenant_id: str) -> str | None:
    # Return bearer token or None to skip this batch
    return cached_tokens.get((agent_id, tenant_id))
```

The token must have scope `9b975845-388f-4429-889e-eab1ef63949c/.default` (resource: Agent 365 Observability) with app role `Agent365.Observability.OtelWrite`.

### Step 2.4 — Set A365 routing attributes on spans

The exporter reads `tenant_id` / `agent_id` (or `a365.tenant_id` / `a365.agent_id`) from span attributes. Two approaches:

**Option A — BaggageBuilder (recommended for request-scoped context):**

```python
from a365_otel_exporter import BaggageBuilder

with BaggageBuilder().tenant_id(TENANT_ID).agent_id(AGENT_ID).build():
    with tracer.start_as_current_span("invoke_agent") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        # ... agent logic ...
```

All spans created within the `BaggageBuilder.build()` context automatically get the routing attributes injected via OTel baggage.

**Option B — Direct span attributes (for one-off spans or background tasks):**

```python
from a365_otel_exporter import set_a365_span_attributes

with tracer.start_as_current_span("invoke_agent") as span:
    set_a365_span_attributes(span, tenant_id=TENANT_ID, agent_id=AGENT_ID)
    span.set_attribute("gen_ai.operation.name", "invoke_agent")
```

### Step 2.5 — Set required span attributes for A365 ingestion

Beyond routing, A365 requires specific attributes per operation type. Set these on every span:

**All spans:**
```python
span.set_attribute("gen_ai.operation.name", "invoke_agent")  # or chat/execute_tool/output_messages
span.set_attribute("gen_ai.agent.id", AGENT_ID)
span.set_attribute("gen_ai.agent.name", "My Agent")
span.set_attribute("microsoft.a365.agent.blueprint.id", AGENT_ID)  # reuse agent_id if no blueprint
span.set_attribute("gen_ai.conversation.id", conversation_id)
span.set_attribute("microsoft.channel.name", "web")  # or msteams, outlook, etc.
span.set_attribute("user.id", user_aad_object_id)
span.set_attribute("client.address", caller_ip)
span.set_attribute("server.address", "myagent.example.com")
span.set_attribute("server.port", "443")  # STRING, not int
```

**`invoke_agent` spans** (additionally):
```python
span.set_attribute("gen_ai.input.messages", '[{"role":"user","content":"..."}]')
span.set_attribute("gen_ai.output.messages", '[{"role":"assistant","content":"..."}]')
```

**`chat` spans** (additionally):
```python
span.set_attribute("gen_ai.request.model", "gpt-4o")
span.set_attribute("gen_ai.provider.name", "openai")
span.set_attribute("gen_ai.usage.input_tokens", "150")   # STRING
span.set_attribute("gen_ai.usage.output_tokens", "42")   # STRING
```

**`execute_tool` spans** (additionally):
```python
span.set_attribute("gen_ai.tool.name", "search_products")
span.set_attribute("gen_ai.tool.type", "function")
span.set_attribute("gen_ai.tool.call.id", "call_abc123")
span.set_attribute("gen_ai.tool.call.arguments", '{"query":"top products"}')
span.set_attribute("gen_ai.tool.call.result", '{"results":[...]}')
```

### Step 2.6 — Complete integration example

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from a365_otel_exporter import A365SpanExporter, A365ExporterOptions, BaggageBuilder
from a365_otel_exporter.auth import create_azure_identity_resolver

# Setup — once at startup
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))  # existing
provider.add_span_processor(BatchSpanProcessor(
    A365SpanExporter(A365ExporterOptions(
        token_resolver=create_azure_identity_resolver(),
    ))
))
tracer = provider.get_tracer("my-agent", "1.0.0")

# Per-request — in the request handler
TENANT_ID = "<customer-tenant-guid>"
AGENT_ID = "<your-agent-aad-app-object-id>"

with BaggageBuilder().tenant_id(TENANT_ID).agent_id(AGENT_ID).build():
    with tracer.start_as_current_span("invoke_agent") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.id", AGENT_ID)
        span.set_attribute("gen_ai.agent.name", "My Agent")
        span.set_attribute("microsoft.a365.agent.blueprint.id", AGENT_ID)
        span.set_attribute("gen_ai.conversation.id", "conv-001")
        span.set_attribute("microsoft.channel.name", "web")
        span.set_attribute("user.id", "<aad-user-objectid>")
        span.set_attribute("client.address", "10.1.2.80")
        span.set_attribute("server.address", "myagent.example.com")
        span.set_attribute("server.port", "443")
        span.set_attribute("gen_ai.input.messages", '[{"role":"user","content":"hello"}]')
        # ... agent logic ...
        span.set_attribute("gen_ai.output.messages", '[{"role":"assistant","content":"hi"}]')
```

## Phase 3 — Verify

Checklist:

```
[ ] a365-otel-exporter installed (with [azure] or [msal] extra)
[ ] A365SpanExporter added as an ADDITIONAL span processor (not replacing existing)
[ ] Token resolver configured and returning valid tokens
[ ] BaggageBuilder (or set_a365_span_attributes) sets tenant_id AND agent_id on every span
[ ] gen_ai.operation.name set on every span (invoke_agent/execute_tool/chat/output_messages)
[ ] All required attributes set per operation type
[ ] Numeric values encoded as strings (token counts, port)
[ ] parentSpanId wiring correct (child spans are children of invoke_agent)
```

Tell the user:
1. Run the agent and check console exporter output for spans
2. Verify in Defender advanced hunting after ~5 minutes (see KQL below)
3. If 200 OK but no data, check: M365 E7 license assigned, tenant consent granted

**Verification KQL:**
```kusto
let agentIdToFind = "YOUR-AGENT-ID";
CloudAppEvents
| where Timestamp > ago(1d)
| where ActionType in ("InvokeAgent", "InferenceCall", "ExecuteToolBySDK")
| extend resData = parse_json(tostring(RawEventData))
| where resData.AgentId == agentIdToFind or resData.TargetAgentId == agentIdToFind
| project Timestamp, ActionType, resData
| order by Timestamp desc
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No spans exported (DEBUG log: "missing tenant_id or agent_id") | BaggageBuilder not wrapping span creation | Ensure BaggageBuilder context encloses all `start_as_current_span` calls |
| Token resolver returns None | Credential not configured or secret expired | Check `create_azure_identity_resolver()` logs; verify credential has access |
| HTTP 401 | Wrong token audience | Scope must be `9b975845-388f-4429-889e-eab1ef63949c/.default` |
| HTTP 403 | Agent ID mismatch or missing permission | URL agent_id must match token's `appid`/`azp` claim; grant `Agent365.Observability.OtelWrite` |
| 200 OK but no data in Defender | Silent drop — no M365 E7 license, or wrong `gen_ai.operation.name` | Ensure at least 1 user has M365 E7 license; use `invoke_agent`/`chat`/`execute_tool`/`output_messages` |
| Token counts show as zero | Sent as int instead of string | Use `span.set_attribute("gen_ai.usage.input_tokens", "150")` — string value |
| Spans appear but run tree broken | Missing parentSpanId or different traceId | Ensure child spans are started within parent span context |
