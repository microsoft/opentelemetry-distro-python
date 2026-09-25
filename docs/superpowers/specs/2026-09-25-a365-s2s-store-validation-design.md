# A365 S2S Store Validation Sample Design

## Goal

Modernize PR #217 so its service-to-service (S2S) sample works against the
current `main` branch, demonstrates every current Agent 365 observability
scope, satisfies the Microsoft Learn Store-publishing telemetry checklist, and
resolves all outstanding review feedback.

The Store contract is the **Validate for store publishing** section of:

<https://learn.microsoft.com/en-us/microsoft-agent-365/developer/observability?tabs=python#validate-for-store-publishing>

For S2S agents, `microsoft.agent.user.id` and
`microsoft.agent.user.email` are not required because the export flow has no
agentic user.

## Branch Integration

Merge `origin/main` into `nikhilc/add-a365-s2s-sample`. Resolve the existing
`README.md` and `pyproject.toml` conflicts by preserving current `main` and
reapplying only the S2S sample changes that are still needed.

The old OpenAI dependency cap is unrelated to the sample and must not be
reintroduced. Current dependency metadata and the root `uv.lock` remain owned
by `main`.

## Review Feedback

Remove the sample-local files called out in review:

- `samples/a365/s2s/.env.example`
- `samples/a365/s2s/pyproject.toml`
- `samples/a365/s2s/uv.lock`

Keep the sample under `samples/a365/s2s/`, as requested and already addressed.
Preserve the previously implemented fixes for tenant consistency, token-cache
identity, and duplicate exporter log handlers.

Move all setup instructions into `samples/a365/s2s/README.md`. The documented
run path uses the repository environment and an ephemeral MSAL dependency, for
example `uv run --with msal python samples/a365/s2s/s2s_exporter.py`. Required
environment variables are set in the shell rather than loaded from a local
`.env` file.

## Sample Behavior

The sample remains self-contained and does not call a real LLM or tool. It
uses realistic simulated operations while exporting real OpenTelemetry spans
when configured with valid S2S credentials.

It demonstrates these public scopes:

1. `InvokeAgentScope` as the root agent invocation.
2. `ApplyGuardrailScope` as a child evaluation before model inference.
3. `InferenceScope` for model input, output, provider, model, token usage, and
   finish reasons.
4. `ExecuteToolScope` for tool arguments, identity, and result.
5. `OutputScope` for the final response, using the invoke-agent context as its
   parent to demonstrate the asynchronous-output pattern.

The invoke-agent scope also records the final response directly so its required
`gen_ai.output.messages` attribute is present.

## Identity and Required Attributes

The sample requires real deployment values for:

- Blueprint application client ID and secret used by the S2S token exchange.
- Tenant ID.
- Agent app instance ID.
- Published agent ID.
- Agent blueprint ID.
- Human caller ID, email, and client IP for the represented request.

The sample uses explicit, non-secret values for the weather-agent name,
description, version, service endpoint, channel, conversation, session, model,
provider, tool, and guardrail metadata. The README explains which illustrative
values must be replaced by an integrating application.

`AgentDetails`, `UserDetails`, `Request`, `CallerDetails`, and
`BaggageBuilder` carry the shared identity and context. The baggage scope
propagates the Store-required attributes to child scopes without duplicating
per-scope setup.

The required Store attributes covered are:

- Invoke agent: agent blueprint/ID/name, caller client address and user
  identity, channel, conversation, input/output messages, operation name,
  server address/port, and tenant.
- Inference: shared identity/context plus input/output messages, provider,
  request model, and operation name.
- Execute tool: shared identity/context plus arguments, call ID, result, tool
  name/type, and operation name.
- Output: shared identity/context plus output messages and operation name.

Agent-user ID and email are intentionally absent for the S2S scenario.

## Configuration and Errors

Required environment variables are validated before telemetry configuration.
Blank values and angle-bracket placeholders fail with a clear message naming
the missing variable and pointing to the README.

The token resolver:

- Uses the requested tenant as the MSAL authority.
- Rejects a requested tenant that differs from the configured credential
  tenant.
- Caches tokens by tenant and agent with a refresh buffer.
- Returns `None` with an actionable error when MSAL acquisition fails.

Exporter debug logging remains scoped to the A365 exporter, does not propagate
to the root logger, and installs only one named handler.

## Validation

Add a focused automated test that executes the sample telemetry path with
export disabled and captures spans in memory. It asserts:

- All five scope operation names are emitted.
- Invoke-agent, inference, execute-tool, and output spans contain the required
  Microsoft Learn Store attributes, except the documented S2S agent-user
  exemption.
- The guardrail span contains its target, decision, guardian identity, and
  finding event.
- The token resolver's existing tenant mismatch and cache behavior remain
  covered by direct unit-level checks where practical.

Run the smallest relevant test selection plus repository formatting, linting,
and type checks that cover the changed sample and test.

## Non-Goals

- Refactoring the existing `samples/a365/manual_telemetry.py`.
- Adding a reusable production token-provider library.
- Changing the A365 scope APIs or exporter behavior.
- Changing package publishing metadata or unrelated dependency constraints.
