# A365 S2S Exporter Sample

A self-contained sample showing how to export [Agent 365](https://learn.microsoft.com/en-us/microsoft-agent-365/) telemetry using the **S2S (service-to-service)** flow.

In the S2S scenario a service authenticates **on its own behalf** using its app
registration credentials — there is **no agentic user**. Two things make this an
S2S sample:

1. `a365_use_s2s_endpoint=True` — routes export to the S2S ingest path.
2. A custom `a365_token_resolver` that performs the MSAL app → instance token
   exchange and acquires an *application* token for the A365 observability scope.

The token resolver mirrors the SDK's FIC flow (`_create_fic_token_resolver` in
`src/microsoft/opentelemetry/a365/core/exporters/utils.py`), but **excludes** the
agentic-user step (`A365_AGENTIC_USER_ID` / `user_fic` grant).

The telemetry is produced with the A365 scope classes (manual instrumentation),
so the sample needs no LLM.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- To actually export: a Blueprint app registration granted the
  `Agent365.Observability.OtelWrite` **application** permission (with admin
  consent). See [`MIGRATION_A365.md`](../../../MIGRATION_A365.md) →
  "Troubleshooting — Permissions and Setup".

## Setup

Install dependencies into a project-managed virtual environment with
[uv](https://docs.astral.sh/uv/) (uv reads `pyproject.toml` and creates
`.venv` automatically):

```bash
uv sync
```

Create your `.env` from the template and fill in your values (`.env` is
gitignored):

```bash
cp .env.example .env
```

The S2S credentials are validated at startup, so all four
`CONNECTIONS__SERVICE_CONNECTION__SETTINGS__*` / `A365_AGENT_APP_INSTANCE_ID`
values must be set even when `ENABLE_A365_OBSERVABILITY_EXPORTER=false`. Set it
to `true` once you have real credentials to export to A365.

## Run

```bash
uv run python s2s_exporter.py
```

The sample enables DEBUG logging for the A365 exporter, so when
`ENABLE_A365_OBSERVABILITY_EXPORTER=true` you'll see the export result on
stderr, for example:

```
DEBUG ...agent365_exporter: HTTP 200 success on attempt 1. Correlation ID: <id>. Response: {... "status":"sent" ...}
```

A non-2xx status (e.g. `HTTP 403`) is logged as an error with the same
correlation ID, which you can use when contacting support.

## Environment variables

| Variable | Description |
| --- | --- |
| `ENABLE_OBSERVABILITY` | Required (`true`) for the A365 scope classes to emit spans. |
| `ENABLE_A365_OBSERVABILITY_EXPORTER` | `true` to send telemetry to the A365 endpoint; `false` still creates spans but skips export. Credentials are required either way. |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID` | Blueprint app registration client ID. |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET` | Blueprint app registration client secret. |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID` | Entra tenant ID. Also used as the exported `AgentDetails.tenant_id`. |
| `A365_AGENT_APP_INSTANCE_ID` | Agent app instance ID used in the `fmi_path` exchange. Falls back to the exported agent ID when `A365_AGENT_ID` is unset. |
| `A365_AGENT_ID` | Optional. Agent ID telemetry is exported for; must match an onboarded agent. Defaults to `A365_AGENT_APP_INSTANCE_ID`. |
