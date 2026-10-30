# Agent 365 Observability

> **Official docs:** [Microsoft OpenTelemetry on Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/microsoft-opentelemetry?tabs=python)

This guide covers A365-specific setup, configuration, and concepts for the `microsoft-opentelemetry` package.
For general config options (Azure Monitor, OTLP, sampling), see the [main README](README.md).
For migrating from standalone A365 packages, see [MIGRATION_A365.md](MIGRATION_A365.md).

## Installation

```bash
pip install microsoft-opentelemetry
```

If you are migrating from the standalone `microsoft-agents-a365-observability-*` packages, see [MIGRATION_A365.md](MIGRATION_A365.md) for step-by-step instructions.

## Configuration

Call `use_microsoft_opentelemetry()` once at startup to initialize Microsoft OpenTelemetry. All keyword arguments are optional; any passed-in value takes priority over the corresponding environment variable.

```python
from microsoft.opentelemetry import use_microsoft_opentelemetry

use_microsoft_opentelemetry(
    enable_a365=True,
    a365_token_resolver=my_token_resolver,
)
```

### A365 Keyword Arguments

| Keyword argument | Type | Default | Env var | Description |
|---|---|---|---|---|
| `enable_a365` | `bool` | `False` | — | Enable A365 span enrichment and exporter setup. |
| `a365_token_resolver` | `Callable` | `None` | — | `(agent_id, tenant_id) -> token` sync callable. If omitted, defaults to FIC / `DefaultAzureCredential`. |
| `a365_cluster_category` | `str` | `"prod"` | `A365_CLUSTER_CATEGORY` | Cluster category (`prod`, `gov`, `dod`, `mooncake`). |
| `a365_use_s2s_endpoint` | `bool` | `False` | `A365_USE_S2S_ENDPOINT` | Use the S2S endpoint. |
| `a365_suppress_invoke_agent_input` | `bool` | `False` | `A365_SUPPRESS_INVOKE_AGENT_INPUT` | Strip input messages from InvokeAgent spans. |
| `a365_enable_observability_exporter` | `bool` | `False` | `ENABLE_A365_OBSERVABILITY_EXPORTER` | Enable the A365 HTTP exporter. When `false`, spans are enriched but not exported to A365. |
| `a365_observability_scope_override` | `str` | `None` | `A365_OBSERVABILITY_SCOPE_OVERRIDE` | Override the authentication scope for the A365 observability service. |
| `a365_max_queue_size` | `int` | `2048` | — | Maximum queue size for the A365 batch span processor. |
| `a365_scheduled_delay_ms` | `int` | `5000` | — | Delay between A365 export batches in milliseconds. |
| `a365_exporter_timeout_ms` | `int` | `30000` | — | Timeout for a single A365 export operation in milliseconds. |
| `a365_max_export_batch_size` | `int` | `512` | — | Maximum batch size for a single A365 export operation. |
| `a365_exporter_disable_offline_storage` | `bool` | `False` | — | Disable durable offline storage. When `True`, failed exports are not persisted to disk and at-least-once delivery is not guaranteed. Defaults to `False` (storage enabled). |
| `a365_exporter_storage_directory` | `str` | `None` | — | Root for an `a365` cache using Azure Monitor's offline storage provider. Configure separate sibling roots for A365 and Azure Monitor; shared or overlapping cache paths are unsupported and are not rejected automatically. `None` uses Azure Monitor's default path resolver with an Agent365 namespace. See [offline storage](#durable-delivery-offline-storage) for security and upgrade guidance. |

### Resource / Service Name

Set `service.name` and `service.namespace` via a `Resource` or environment variables:

```python
from opentelemetry.sdk.resources import Resource
from microsoft.opentelemetry import use_microsoft_opentelemetry

use_microsoft_opentelemetry(
    enable_a365=True,
    resource=Resource.create({
        "service.name": "my-agent",
        "service.namespace": "my-namespace",
    }),
    a365_token_resolver=my_token_resolver,
)
```

Or using environment variables:

```bash
export OTEL_SERVICE_NAME=my-agent
export OTEL_RESOURCE_ATTRIBUTES="service.namespace=my-namespace"
```

### Exporter Batch Options

The A365 exporter batch processor defaults can be overridden via the `a365_*` kwargs listed in the table above.

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    a365_token_resolver=my_token_resolver,
    a365_max_queue_size=4096,
    a365_scheduled_delay_ms=2000,
    a365_exporter_timeout_ms=15000,
    a365_max_export_batch_size=256,
)
```

### Durable Delivery (Offline Storage)

When `a365_enable_observability_exporter=True`, the A365 exporter persists failed export payloads to disk and replays them once connectivity is restored — providing **at-least-once delivery** semantics.

Key defaults and limits:

| Property | Value |
|---|---|
| Enabled by default | Yes (when exporter is active) |
| Retention window | 2 days |
| Maximum storage size | 50 MiB (upstream capacity check before each write; one write can cross the limit) |
| Storage path | Platform default (see below) |

Agent365 uses the **same `LocalFileStorage` provider as Azure Monitor**, not a
separate SQLite queue. The provider owns atomic JSON-blob writes, rename-based
leases, expiration, capacity checks, maintenance, and platform permissions.
Agent365 only adapts identity envelopes and its authenticated replay protocol.
Processes using the same cache can coordinate replay through those file leases.

For an explicitly configured root, Agent365 records live in `<root>/a365/`.
Azure Monitor uses its configured storage directory directly. When both
exporters are enabled, configure **separate sibling roots**, as in the example
below, so neither effective cache directory contains the other. Reusing the
same root does not isolate capacity: Azure Monitor recursively counts files
in its directory, including an `a365` child. Configurations that resolve to
the same effective cache directory can also cause either exporter to claim
or delete the other's incompatible records. **Shared or overlapping cache paths
are unsupported and are not detected or rejected automatically.** Customers
must keep their resolved paths separate, including any filesystem aliases.

With no configured root, Agent365 calls Azure Monitor's
`_get_storage_directory("agent365")`: the resulting cache is
under the system temporary directory, in
`Microsoft-AzureMonitor-<hash>/opentelemetry-python-agent365`. The upstream hash
includes the namespace, user, process name, and application directory. Reusing
the same resulting path preserves blob replay across restarts. Temporary-directory
cleanup by the operating system can remove queued records; configure persistent
storage when restart durability must survive that cleanup.

**Replay behavior:**

- Each queued record stores only its identity (tenant, agent, agentic user, S2S flag) and payload — not a fixed URL. On replay, the exporter reconstructs the export endpoint from the exporter's *current* configuration and re-resolves a fresh bearer token, so records queued before an endpoint or credential change are still delivered correctly, and any endpoint that would not resolve to HTTPS is rejected rather than replayed.
- Records that are permanently rejected by the service (e.g. `400 Bad Request`) or that fail internal validation (unsupported schema version, blank tenant/agent id, or blank payload — "poison" records) are discarded from the durable queue instead of being retried forever.
- Unreadable blobs are logged and retained for retry or retention expiry. The provider does not distinguish malformed JSON from transient read errors, so an unreadable blob is not treated as a proven poison record.
- `shutdown()` is drain-safe: it signals the background replay loop to stop and blocks until any in-flight replay send actually finishes before closing the durable store and HTTP session, so an in-progress send is never left holding a closed resource and no accepted span is dropped mid-flight. Concurrent `shutdown()` callers all wait for that same cleanup to complete.

**To disable durable storage** (no disk writes, best-effort delivery only):

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    a365_enable_observability_exporter=True,
    a365_exporter_disable_offline_storage=True,
)
```

**To configure both exporters with separate storage roots:**

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    a365_enable_observability_exporter=True,
    enable_azure_monitor=True,
    a365_exporter_storage_directory=r"C:\MyApp\Telemetry\Agent365",
    azure_monitor_exporter_storage_directory=r"C:\MyApp\Telemetry\AzureMonitor",
)
```

The resulting cache directories are `C:\MyApp\Telemetry\Agent365\a365` and
`C:\MyApp\Telemetry\AzureMonitor`. On Unix, use absolute sibling roots such as
`/var/lib/my-agent/telemetry/Agent365` and
`/var/lib/my-agent/telemetry/AzureMonitor`, provisioned with appropriate
service-account ownership and permissions. Configure the Azure Monitor
connection string or credential as usual. The same independent exporter-root
configuration is supported by the .NET SDK; Python's existing `a365` child
layout and provider permission handling remain unchanged.

> **Security note:** Stored OTLP payloads are unencrypted. With sensitive-data capture enabled (`enable_sensitive_data=True`), payloads may include prompts, completions, or tool arguments. Do not configure a shared temporary directory such as `/tmp` as a customer storage root: a predictable child in a shared parent can be replaced or precreated. Normally provision a private, service-account-owned `0700` root and review its ACLs, ancestors, and protection against path replacement. Cache permissions do not isolate data from root, administrators, or other processes using the same account.

The implementation inspected is Azure Monitor Python exporter **1.0.0b58**, pinned
in `uv.lock`, at commit
[`83907dc9ed2eb8c742b353b5f2cf276e039026da`](https://github.com/Azure/azure-sdk-for-python/blob/83907dc9ed2eb8c742b353b5f2cf276e039026da/sdk/monitor/azure-monitor-opentelemetry-exporter/azure/monitor/opentelemetry/exporter/_storage.py).
Unlike the .NET provider, this Python provider creates its cache directory and,
on Linux/macOS, opens the final directory without following a symlink, checks
that the owner is the current user or root, and applies `0700` with `fchmod`.
It creates blob temporary files exclusively with mode `0600` before renaming
them. On Windows it grants the current user and administrators access and
removes inherited ACLs using `icacls`. Agent365 neither duplicates nor bypasses
these upstream cache protections.

On Linux/macOS, Agent365 additionally checks the explicitly configured root
before initializing the provider on its `a365` child. The configured path is
normalized with `os.path.abspath`, matching the provider, before root validation
and legacy-backlog detection. The root must be a real
directory (not a symlink), owned by the current user or root, and not writable
by group or others. Unsafe roots disable offline delivery without permission
repair. A missing root is created with mode `0700` (subject to umask) and checked
after creation as well. Existing root permissions are preserved; upstream
checks and permission enforcement still apply to the existing or newly created
`a365` child. Windows behavior and the implicit default resolver are unchanged.
Creation of missing ancestors follows ordinary filesystem defaults.

These point-in-time checks do not validate ancestor ownership, ACLs, or
protection against subsequent path replacement. Customers remain responsible
for provisioning and protecting the entire path; the checks are not a
confidentiality guarantee.

Storage is initialized lazily on first export. Invalid configuration (including
blank paths), provider setup failure, or an initialization exception logs an
error and disables **only offline buffering and replay**; online export continues.
An explicitly configured path never falls back to another location on failure.
Explicit disablement bypasses storage initialization altogether.

**Breaking change and existing backlogs (all platforms):** the SQLite format,
explicit-root layout, and implicit default location have changed. Existing
`queue.db`, `queue.db-wal`, and `queue.db-shm` files are **not** opened, converted,
deleted, or automatically migrated. **Required before upgrading:** restore connectivity and
drain the old queue using the previous SDK and original configuration, then shut
down all writers cleanly. Verify delivery before retiring the old directory.
This is a customer-managed upgrade prerequisite, not an SDK migration step.
If draining cannot be completed, retain a secured, coherent SQLite backup
(including any necessary WAL/SHM state) for controlled recovery with the previous
SDK; copying or renaming SQLite files into the new blob cache does not migrate
them. A detected `queue.db` in an explicitly configured root produces a warning.
No old implicit temporary/home-directory backlog is discovered automatically.

To locate a previous implicit queue, inspect the old SDK's service environment.
On Unix, its normal parent was `$XDG_STATE_HOME/a365-durable-queue` when
`XDG_STATE_HOME` was nonempty, otherwise `~/.local/state/a365-durable-queue`. On
Windows, it was `%LOCALAPPDATA%\a365-durable-queue`, with a system-temporary
fallback when `LOCALAPPDATA` was unset. Unix also used a temporary fallback if
the home directory could not be resolved and `XDG_STATE_HOME` was unset.
Each queue was in a child named by the first 16 hexadecimal characters of
`sha256((getpass.getuser() + sys.executable + str(Path.cwd())).encode())`.
Changes to the service account, Python executable, or working directory can
leave multiple old queue directories. Identify them before upgrading and use
the previous SDK in the original environment to drain them; do not assume that
successful replay of new JSON blobs proves recovery of an old SQLite backlog.
Reusing an old directory alone does not convert its SQLite records.

## Auto-Instrumented Libraries

It auto-discovers and activates supported instrumentors via OpenTelemetry entry points. No manual `instrument()` calls are needed.

Supported instrumentors:

| Library | Instrumentor | Package |
|---|---|---|
| Semantic Kernel | `SemanticKernelInstrumentor` | Bundled |
| OpenAI Agents SDK | `A365OpenAIAgentsInstrumentor` (A365) / `opentelemetry-instrumentation-openai-agents-v2` (non-A365) | Bundled / Dependency |
| Agent Framework | `AgentFrameworkInstrumentor` | Bundled |
| LangChain | `LangChainInstrumentor` | Bundled |

### OpenAI Agents SDK — Dual Instrumentation

**Two** instrumentors for the OpenAI Agents SDK, selected automatically based on whether A365 is enabled:

| Mode | Instrumentor | Span format |
|---|---|---|
| `enable_a365=True` | `A365OpenAIAgentsInstrumentor` (bundled) | A365 structured array format with `custom.parent.span.id`, per-message indexed attributes, detailed token counts, `graph_node_parent_id` for handoffs |
| `enable_a365=False` | `opentelemetry-instrumentation-openai-agents-v2` (upstream) | Standard OpenTelemetry GenAI semantic conventions |

The selection is automatic — no manual `instrument()` calls are needed. When `enable_a365=True`, the upstream instrumentor for `openai_agents` is **skipped** and the A365 instrumentor is used instead. All other instrumentors (LangChain, Semantic Kernel, etc.) are unaffected.

> **Important:** When both `enable_a365=True` and `enable_azure_monitor=True` are set, Azure Monitor and OTLP exporters will see spans in the A365 format (structured array) rather than upstream OTel format. This is expected — the A365 instrumentor writes to the global `TracerProvider`, so all attached exporters receive the same spans.

### Noisy Spans — A365-Only Mode

When `enable_a365=True` (and `enable_azure_monitor` is **not** set), the **web-framework and HTTP-client instrumentations are disabled by default** so only GenAI-related spans appear:

| Library | Default with A365 only |
|---|---|
| `django` | disabled |
| `fastapi` | disabled |
| `flask` | disabled |
| `httpx` | disabled |
| `httpx2` | disabled |
| `psycopg2` | disabled |
| `requests` | disabled |
| `urllib` | disabled |
| `urllib3` | disabled |
| `azure_sdk` | disabled |
| `openai` | enabled |
| `openai_agents` | enabled |
| `langchain` | enabled |
| `semantic_kernel` | enabled |
| `agent_framework` | enabled |

> **Note:** When both `enable_a365=True` and `enable_azure_monitor=True` are set, all instrumentations remain **enabled** so Azure Monitor continues to receive web/HTTP telemetry.

To re-enable a disabled instrumentation:

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    instrumentation_options={
        "fastapi": {"enabled": True},
    },
)
```

To disable a specific instrumentation:

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    instrumentation_options={
        "langchain": {"enabled": False},
    },
)
```

## Hosting Middleware

If your agent uses the Agent Hosting framework, use `ObservabilityHostingManager` to register middleware automatically.

> **Important:** Both `enable_baggage` and `enable_output_logging` default to `False`. You must explicitly enable them or baggage won't propagate and `output_messages` spans won't be emitted.

```python
from microsoft.opentelemetry.a365.hosting import (
    ObservabilityHostingManager,
    ObservabilityHostingOptions,
)

ObservabilityHostingManager.configure(
    adapter.middleware_set,
    ObservabilityHostingOptions(
        enable_baggage=True,         # Required for baggage propagation
        enable_output_logging=True,  # Required for output_messages spans
    ),
)
```

| Option | Default | Description |
|---|---|---|
| `enable_baggage` | `False` | Enable baggage middleware that extracts tenant, agent, user, channel from `TurnContext`. |
| `enable_output_logging` | `False` | Enable output logging middleware that records `output_messages` spans. |

## Baggage

Baggage sets per-request context (tenant, agent, user) that flows to recognized GenAI spans only. **Without `tenant_id` and `agent_id`, the exporter silently drops spans.**

A span is recognized as GenAI at span start by evaluating these signals in order: a supported `gen_ai.operation.name` attribute; if that attribute is present but unrecognized (`chain`, `embeddings`, `text_completion`, `generate_content`, `create_agent`, ...) it is authoritative, so baggage and span-name inference are skipped and only the instrumentation scope can still classify the span; otherwise a span name matching a supported operation (`invoke_agent ...`, `chat ...`, ...) or a known pre-rename name (`chat.completions ...`), then a recognized `gen_ai.operation.name` baggage entry, then a supported GenAI instrumentation scope (`Agent365Sdk`, `semantic_kernel.*`, `agent_framework`, `microsoft.opentelemetry._genai.*`, `opentelemetry.instrumentation.openai_v2`, `opentelemetry.instrumentation.openai_agents`). The scope signal matters because LangChain, Semantic Kernel, Agent Framework, and OpenAI Agents all set `gen_ai.operation.name` *after* the span starts — a LangChain chat span begins life named `ChatOpenAI`, and a Semantic Kernel one as `chat.completions gpt-4o`.

Spans classified only by instrumentation scope are GenAI with an unknown operation: they receive the common baggage attributes, but never the `invoke_agent`-only ones (caller agent details, `server.address`, `server.port`).

### BaggageBuilder

```python
from microsoft.opentelemetry.a365.core import BaggageBuilder, InvokeAgentScope

with (
    BaggageBuilder()
    .tenant_id("contoso-tenant")
    .agent_id("weather-agent-001")
    .user_id("user-42")
    .user_email("alice@contoso.com")
    .channel_name("msteams")
    .session_id("session-abc")
    .conversation_id("conv-789")
    .build()
):
    # All spans created here inherit these attributes
    with InvokeAgentScope.start(...) as scope:
        ...
```

To copy an application-specific baggage value onto Agent365 GenAI spans,
explicitly opt in each key with `custom_attribute()` or `custom_attributes()`:

```python
with (
    BaggageBuilder()
    .tenant_id("contoso-tenant")
    .agent_id("weather-agent-001")
    .custom_attribute("customer.tier", "gold")
    .custom_attributes({"customer.region": "west"})
    .build()
):
    with InvokeAgentScope.start(...) as scope:
        ...
```

`set_pairs()` only sets baggage. It does not opt arbitrary baggage keys into
span attributes; use `custom_attribute()` for any custom key that should appear
on recognized Agent365 GenAI spans. Baggage propagation never overwrites
attributes already present on the current span. Baggage-propagated values are
applied when the span starts, so they precede later `record_attributes()` calls
when duplicate-key protection is also present; direct/current span attributes
remain authoritative.

A span is recognized as GenAI at span start by evaluating these signals in
order: a supported `gen_ai.operation.name` attribute; if that attribute is
present but unrecognized (`chain`, `embeddings`, `text_completion`,
`generate_content`, `create_agent`, ...) it is authoritative, so baggage and
span-name inference are skipped and only the instrumentation scope can still
classify the span; otherwise a recognized `gen_ai.operation.name` baggage entry,
then a span name matching a supported operation (`invoke_agent ...`,
`chat ...`, ...) or a known pre-rename name (`chat.completions ...`), then a
supported GenAI instrumentation scope (`Agent365Sdk`, `semantic_kernel.*`,
`agent_framework`, `microsoft.opentelemetry._genai.*`,
`opentelemetry.instrumentation.openai_v2`,
`opentelemetry.instrumentation.openai_agents`). Spans classified only by
instrumentation scope are GenAI with an unknown operation: opted-in custom
baggage applies to them, but `invoke_agent`-only attributes never do.

### From TurnContext (Hosting Framework)

```python
from microsoft.opentelemetry.a365.core import BaggageBuilder
from microsoft.opentelemetry.a365.hosting.scope_helpers.populate_baggage import populate

async def on_message(context: TurnContext, _state: TurnState):
    builder = BaggageBuilder()
    populate(builder, context)  # Extracts tenant, agent, user, channel from activity

    with builder.build():
        ...
```

### Baggage Middleware (Automatic)

```python
from microsoft.opentelemetry.a365.hosting import (
    ObservabilityHostingManager,
    ObservabilityHostingOptions,
)

ObservabilityHostingManager.configure(
    adapter.middleware_set,
    ObservabilityHostingOptions(enable_baggage=True),
)
```

## Token Resolver

The exporter authenticates with a Bearer token. Provide a sync callable `(agent_id, tenant_id) -> str | None`.

### Manual

```python
from microsoft.opentelemetry import use_microsoft_opentelemetry
from microsoft.opentelemetry.a365.runtime import get_observability_authentication_scope

_cached_token: str | None = None

def my_token_resolver(agent_id: str, tenant_id: str) -> str | None:
    return _cached_token

use_microsoft_opentelemetry(enable_a365=True, a365_token_resolver=my_token_resolver)

@AGENT_APP.activity("message", auth_handlers=["AGENTIC"])
async def on_message(context: TurnContext, _state: TurnState):
    global _cached_token
    _cached_token = await AGENT_APP.auth.exchange_token(
        context,
        scopes=get_observability_authentication_scope(),
        auth_handler_id="AGENTIC",
    )
```

### Agentic Token Cache (Agent Framework Apps)

```python
from microsoft.opentelemetry import use_microsoft_opentelemetry
from microsoft.opentelemetry.a365.hosting.token_cache_helpers import AgenticTokenCache, AgenticTokenStruct
from microsoft.opentelemetry.a365.runtime import get_observability_authentication_scope

token_cache = AgenticTokenCache()

_cached_tokens: dict[tuple[str, str], str | None] = {}

# Keep the sync resolver side-effect free; refresh the cache in the async request handler.
def sync_token_resolver(agent_id: str, tenant_id: str) -> str | None:
    return _cached_tokens.get((agent_id, tenant_id))

use_microsoft_opentelemetry(enable_a365=True, a365_token_resolver=sync_token_resolver)

@AGENT_APP.activity("message", auth_handlers=["AGENTIC"])
async def on_message(context: TurnContext, _state: TurnState):
    agent_id = context.activity.recipient.id
    tenant_id = context.activity.recipient.tenant_id
    token_cache.register_observability(
        agent_id=agent_id,
        tenant_id=tenant_id,
        token_generator=AgenticTokenStruct(authorization=AGENT_APP.auth, turn_context=context),
        observability_scopes=get_observability_authentication_scope(),
    )
    _cached_tokens[(agent_id, tenant_id)] = await token_cache.get_observability_token(
        agent_id,
        tenant_id,
    )
```

### FIC / DefaultAzureCredential (Automatic)

When no `a365_token_resolver` is provided, Microsoft OpenTelemetry tries FIC using `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__*` env vars, then falls back to `DefaultAzureCredential`.

## Manual Instrumentation

Use scope classes when auto-instrumentation isn't available or you need fine-grained control.
`record_attributes()` accepts dictionaries or iterable key/value pairs for custom
dimensions, but it never overwrites span attributes that were already set by scope
construction, by attributes propagated from baggage through `A365SpanProcessor`,
or by earlier `record_attributes()` calls. Blank keys are skipped.

### InvokeAgentScope

Top-level agent invocation — wraps the entire request/response cycle:

```python
from microsoft.opentelemetry.a365.core import (
    AgentDetails, CallerDetails, Channel, GenAiRequestParameters,
    GenAiResponseParameters, InvokeAgentScope, InvokeAgentScopeDetails,
    Request, ServiceEndpoint, TextPart, UserDetails,
)

agent = AgentDetails(agent_id="agent-001", agent_name="My Agent", tenant_id="t1")

with InvokeAgentScope.start(
    request=Request(content="Hello", session_id="s1", conversation_id="c1", channel=Channel(name="msteams")),
    scope_details=InvokeAgentScopeDetails(
        endpoint=ServiceEndpoint(hostname="agent.contoso.com"),
        request_parameters=GenAiRequestParameters(
            model="gpt-4o",
            max_tokens=256,
            temperature=0.2,
            stop_sequences=["END"],
            output_type="text",
            system_instructions=[TextPart(content="Be concise.")],
        ),
    ),
    agent_details=agent,
    caller_details=CallerDetails(user_details=UserDetails(user_id="u1", user_email="u@contoso.com")),
) as scope:
    # ... do work ...
    scope.record_response_parameters(
        GenAiResponseParameters(
            finish_reasons=["stop"],
            input_tokens=42,
            output_tokens=18,
            cache_write_input_tokens=4,
        )
    )
    scope.record_response("Here is the answer.")
```

`GenAiRequestParameters` values are recorded when the scope starts. Use
`scope.record_response_parameters()` for response values that are only known
after completion. Fields left as `None` are omitted from the span. Sequence
fields such as `stop_sequences` and `finish_reasons` are emitted as
OpenTelemetry string arrays.

Supported semantic attributes:

- Request: `gen_ai.request.model`, `gen_ai.request.seed`,
  `gen_ai.request.choice.count`, `gen_ai.request.frequency_penalty`,
  `gen_ai.request.max_tokens`, `gen_ai.request.presence_penalty`,
  `gen_ai.request.stop_sequences`, `gen_ai.request.temperature`,
  `gen_ai.request.top_p`, `gen_ai.data_source.id`, `gen_ai.output.type`,
  `gen_ai.system_instructions`
- Response: `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_write.input_tokens`,
  `gen_ai.usage.cache_read.input_tokens`

### ExecuteToolScope

Pass `Request(session_id="session-123")` to correlate execute-tool and inference
spans using `microsoft.session.id`, as with invoke-agent spans. The session ID is
recorded directly from the request without requiring a baggage builder or span
processor. Omitting it leaves the attribute unset, and `conversation_id` remains
an independent correlation field.

```python
from microsoft.opentelemetry.a365.core import ExecuteToolScope, ToolCallDetails, Request

with ExecuteToolScope.start(
    request=Request(content="What's the weather?"),
    details=ToolCallDetails(tool_name="get_weather", tool_call_id="call_1", arguments={"city": "Seattle"}),
    agent_details=agent,
) as scope:
    result = get_weather("Seattle")
    scope.record_response(result)
```

For remote tools, pass a full endpoint URL to retain its path and query in `url.full`:

```python
from microsoft.opentelemetry.a365.core import ServiceEndpoint, ToolCallDetails

details = ToolCallDetails(
    tool_name="get_weather",
    endpoint=ServiceEndpoint.from_url("https://tools.example.test:8443/api/weather"),
)
```

`ServiceEndpoint.from_url()` requires an absolute URL with a hostname and a valid port.
It derives `server.address` and `server.port` while preserving the original full URL.
As before, port `443` is omitted on execute-tool spans.
Existing `ServiceEndpoint(hostname="tools.example.test", port=8443)` calls remain valid
and do not invent or emit a full URL. A full URL can also be supplied via the optional
`ServiceEndpoint.url` field alongside the existing hostname and port.
Only execute-tool scopes emit this URL attribute; other scopes retain their existing behavior.

**Privacy:** Full URLs are recorded as supplied, including paths and query parameters.
Do not pass URLs containing credentials, access tokens, personal data or other secrets;
sanitize them before constructing the endpoint. URL capture is not gated by
`enable_sensitive_data`.

`ToolCallDetails.arguments` and `ExecuteToolScope.record_response()` also accept typed execute-tool schema models.
Typed top-level arguments and results serialize to the Agent365 JSON contract with `schema_version: "1.0"`,
while raw dictionaries and strings remain supported and keep their existing behavior.

```python
from microsoft.opentelemetry.a365.core import (
    ExecuteToolCallArguments,
    ExecuteToolCallResult,
    ExecuteToolScope,
    ToolCallAction,
    ToolCallDetails,
    ToolCallOutcomeStatus,
    ToolCallResource,
    ToolCallResultOutcome,
    ToolCallResultPagination,
    Request,
)

arguments = ExecuteToolCallArguments(
    action=ToolCallAction.READ,
    resources=[
        ToolCallResource(
            resource_id="file-1",
            uri="https://contoso.example/files/1",
            name="Forecast",
            resource_type="file",
            provider="sharepoint",
        )
    ],
    parameters={"city": "Seattle"},
    extension_data={"provider_operation": "weather.lookup"},
)

with ExecuteToolScope.start(
    request=Request(content="What's the weather?"),
    details=ToolCallDetails(tool_name="get_weather", tool_call_id="call_1", arguments=arguments),
    agent_details=agent,
) as scope:
    scope.record_response(
        ExecuteToolCallResult(
            outcome=ToolCallResultOutcome(status=ToolCallOutcomeStatus.SUCCESS),
            data={"temperature_f": 68},
            pagination=ToolCallResultPagination(has_more=False, total_count=1),
        )
    )
```

The typed arguments above generate a JSON payload shaped like:

```json
{
  "schema_version": "1.0",
  "action": "read",
  "resources": [
    {
      "id": "file-1",
      "uri": "https://contoso.example/files/1",
      "name": "Forecast",
      "type": "file",
      "provider": "sharepoint"
    }
  ],
  "parameters": {"city": "Seattle"},
  "metadata": {
    "provider_operation": "weather.lookup"
  }
}
```

#### Schema enums

`action`, `outcome.status`, and `policy.decision` are constrained to the same tokens as the .NET distro:

| Field | Enum | Tokens |
| --- | --- | --- |
| `ExecuteToolCallArguments.action` | `ToolCallAction` | `create`, `read`, `update`, `delete` |
| `ToolCallResultOutcome.status` | `ToolCallOutcomeStatus` | `success`, `failure` |
| `ToolCallResultPolicy.decision` | `ToolPolicyDecision` | `allow`, `deny` |

The exact lowercase strings are accepted as well, so `action="read"` and `action=ToolCallAction.READ` are
equivalent. Any other value — a different casing, an undefined token, a number, a boolean, or a member of a
different enum — is rejected instead of emitting schema-invalid telemetry.

#### Null handling and extension data

Model properties that are `None` are omitted. `False`, zero, empty strings, empty dictionaries, and empty
lists are preserved. `None` inside a dictionary or list you supply (for example `parameters`, `data`, or
`extension_data`) is preserved as JSON `null`, matching the .NET contract.

`extension_data` is serialized under a `metadata` property on the same model. The public Python field name
remains `extension_data`, while the JSON wire contract consistently uses `metadata`. Empty extension
dictionaries omit `metadata`.

Each extensible nested model owns its own metadata object. Extension keys therefore cannot replace declared
properties such as `action`, `schema_version`, `outcome.status`, or `policy.decision`; a matching extension key
remains inside `metadata`.

#### Serialization failures

Typed payload serialization never raises and never leaves a span orphaned. If any value cannot be
represented — an unsupported type, a reference cycle, `NaN`/`Infinity`, or an undefined enum token — the
whole attribute value is replaced by the diagnostic payload and a warning is logged:

```json
{"serialization_error": "Failed to serialize execute tool payload."}
```

`bytes` and `bytearray` are emitted as base64 strings, `datetime`/`date`/`time` as ISO-8601 strings (using
the `Z` designator for UTC), `UUID` as its canonical string, and `Decimal` as a precision-preserving JSON
number. Any `Enum` is emitted as its value, and lists, tuples, sets, and other sized collections as JSON
arrays. Raw dictionary arguments and results keep their existing
serialization but also fall back to the same diagnostic payload instead of raising.

### InferenceScope

```python
from microsoft.opentelemetry.a365.core import (
    InferenceCallDetails, InferenceOperationType, InferenceScope, Request, ServiceEndpoint,
)

with InferenceScope.start(
    request=Request(content="What's the weather?"),
    details=InferenceCallDetails(
        operationName=InferenceOperationType.CHAT, model="gpt-4o", providerName="openai",
        endpoint=ServiceEndpoint(hostname="api.openai.com"),
    ),
    agent_details=agent,
) as scope:
    completion = call_llm(...)
    scope.record_input_tokens(45)
    scope.record_output_tokens(20)
    scope.record_finish_reasons(["stop"])
```

### OutputScope

For async scenarios where the parent scope has ended but you need to record output later:

```python
from microsoft.opentelemetry.a365.core import OutputScope, Response, SpanDetails

parent_ctx = invoke_scope.get_context()  # Save before parent ends

with OutputScope.start(
    request, Response(messages="Final answer"), agent_details,
    span_details=SpanDetails(parent_context=parent_ctx),
):
    pass  # Output recorded from Response
```

## Validate Locally

Use the console exporter to verify spans are emitted correctly before deploying.

### Console-Only (No A365 Export)

Set `enable_a365=True` but leave the A365 HTTP exporter disabled. Spans are enriched with A365 attributes and printed to stdout:

```python
from microsoft.opentelemetry import use_microsoft_opentelemetry

use_microsoft_opentelemetry(
    enable_a365=True,
    enable_console=True,
    # a365_enable_observability_exporter defaults to False,
    # so spans are NOT sent to the A365 service.
)
```

### Console + A365 Export

To see console output **and** export to A365 simultaneously:

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    enable_console=True,
    a365_enable_observability_exporter=True,
    a365_token_resolver=my_token_resolver,
)
```

### Debug Logging

Enable verbose logging to diagnose export issues:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("microsoft.opentelemetry.a365.core").setLevel(logging.DEBUG)

# Or target only the exporter:
logging.getLogger(
    "microsoft.opentelemetry.a365.core.exporters.agent365_exporter"
).setLevel(logging.DEBUG)
```

Key log messages to look for:

```
DEBUG  Token resolved for agent {agentId} tenant {tenantId}
DEBUG  Exporting {n} spans to {url}
DEBUG  HTTP 200 - correlation ID: abc-123
ERROR  Token resolution failed: {error}
ERROR  HTTP 401 exporting spans - correlation ID: abc-123
INFO   No spans with tenant/agent identity found; nothing exported.
```

## Troubleshooting

See the [official troubleshooting guide](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/microsoft-opentelemetry?tabs=python#troubleshooting) on Microsoft Learn.

## Samples

See the [samples/a365/](samples/a365/) directory for runnable examples.
