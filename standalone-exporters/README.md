# a365-otel-exporter

A standalone OpenTelemetry `SpanExporter` that sends trace data to the
Agent 365 (A365) Observability service. Designed for teams that already have
an OpenTelemetry setup and want to add A365 as an additional export
destination -- no other SDK changes required.

## Install

```bash
pip install a365-otel-exporter

# For automatic Azure Identity token resolution:
pip install a365-otel-exporter[azure]

# For MSAL confidential-client token resolution:
pip install a365-otel-exporter[msal]
```

## Quick Start

Add the exporter to your existing `TracerProvider`:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from a365_otel_exporter import A365SpanExporter, A365ExporterOptions, BaggageBuilder
from a365_otel_exporter.auth import create_azure_identity_resolver

# 1. Create the exporter with a token resolver
exporter = A365SpanExporter(
    A365ExporterOptions(
        token_resolver=create_azure_identity_resolver(),
        # endpoint defaults to https://agent365.svc.cloud.microsoft
    )
)

# 2. Add it to your TracerProvider (alongside any existing exporters)
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(exporter))

# 3. Set A365 baggage so the exporter knows where to route spans
tracer = provider.get_tracer("my-agent")

with BaggageBuilder().tenant_id("YOUR_TENANT_ID").agent_id("YOUR_AGENT_ID").build():
    with tracer.start_as_current_span("invoke_agent") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        # ... your agent logic ...
```

## Token Resolvers

The exporter needs a bearer token to authenticate with A365. Provide a
callable with signature `(agent_id: str, tenant_id: str) -> Optional[str]`.

### Azure Identity (recommended for Azure-hosted workloads)

```python
from a365_otel_exporter.auth import create_azure_identity_resolver

resolver = create_azure_identity_resolver()
# Uses DefaultAzureCredential -- works with managed identity, CLI, etc.
```

### MSAL Confidential Client (service-to-service)

```python
from a365_otel_exporter.auth import create_msal_resolver

resolver = create_msal_resolver(
    client_id="YOUR_APP_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    tenant_id="YOUR_AAD_TENANT_ID",
)
```

### Custom resolver

```python
def my_resolver(agent_id: str, tenant_id: str) -> str:
    return fetch_token_from_vault()

exporter = A365SpanExporter(A365ExporterOptions(token_resolver=my_resolver))
```

## Setting A365 Span Attributes

The exporter groups spans by `(tenant_id, agent_id)` and routes each group
to the correct A365 ingestion endpoint. These values can be set in two ways:

### Option A: BaggageBuilder (recommended)

```python
with BaggageBuilder().tenant_id("...").agent_id("...").build():
    with tracer.start_as_current_span("invoke_agent") as span:
        ...
```

### Option B: Direct span attributes

```python
from a365_otel_exporter import set_a365_span_attributes

with tracer.start_as_current_span("invoke_agent") as span:
    set_a365_span_attributes(span, tenant_id="...", agent_id="...")
```

## Required Span Attributes

The A365 backend processes spans based on the `gen_ai.operation.name`
attribute. Set this attribute on every span you want A365 to ingest.

| gen_ai.operation.name | Description                          |
|-----------------------|--------------------------------------|
| invoke_agent          | Top-level agent invocation           |
| execute_tool          | Tool/plugin execution within an agent|
| chat                  | LLM chat completion call             |
| output_messages       | Final output message generation      |

NOTE: Spans with other `gen_ai.operation.name` values (or without the
attribute) are accepted by the endpoint but filtered server-side during
ingestion processing. Only the four values above produce observable data
in the A365 dashboards.

## Configuration Reference

| Option            | Type                                    | Default                                       |
|-------------------|-----------------------------------------|-----------------------------------------------|
| token_resolver    | (agent_id, tenant_id) -> Optional[str]  | (required)                                    |
| endpoint          | str                                     | https://agent365.svc.cloud.microsoft          |
| timeout_seconds   | int                                     | 30                                            |

## Preprod / Test Environments

For non-production environments, override the endpoint:

```python
options = A365ExporterOptions(
    token_resolver=resolver,
    endpoint="https://preprod.agent365.svc.cloud.dev.microsoft",
)
```

## License

MIT
