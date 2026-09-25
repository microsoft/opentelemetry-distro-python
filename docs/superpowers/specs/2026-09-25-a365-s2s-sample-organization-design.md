# Agent 365 S2S Sample Organization Design

## Goal

Separate service-to-service authentication from the executable telemetry sample
without changing the documented run command, emitted spans, environment
contract, or token behavior.

## Reference Structure

The .NET S2S demo in `microsoft/opentelemetry-distro-dotnet` separates:

- `Program.cs` for orchestration.
- `SampleOptions.cs` for validated configuration.
- `S2STokenProvider.cs` for identity checks and caching.
- `MsalTokenExchangeClient.cs` for the two MSAL exchanges.
- `SampleScenario.cs` for deterministic telemetry.

The Python sample will preserve those responsibility boundaries while using
fewer abstractions appropriate for a small script.

## Structure

### `samples/a365/s2s/sample_config.py`

Owns the validated sample settings:

- Environment-variable names.
- Required-value and placeholder validation.
- An immutable `SampleConfig` data object.
- Construction of `AgentDetails`, `UserDetails`, and the deterministic
  `Request`.

Secrets remain encapsulated in the configuration object and are never logged
or included in its representation.

### `samples/a365/s2s/token_resolver.py`

Owns the authentication boundary:

- MSAL import guidance.
- Blueprint-to-agent-instance token exchange.
- Tenant and agent-instance identity validation.
- Thread-safe token caching and refresh-buffer behavior.

`build_s2s_token_resolver(config)` is the public sample-facing API. The returned
callable retains the existing `(agent_id, tenant_id) -> token | None` contract.
The MSAL exchange remains in this module rather than adding the .NET sample's
interface and result types, which would add indirection without improving the
Python demonstration.

### `samples/a365/s2s/sample_scenario.py`

Owns the deterministic Store-validation trace:

- Baggage construction.
- Invoke-agent scope.
- Guardrail decision and finding.
- Inference scope and messages.
- Execute-tool scope and result.
- Invoke result and output scope.

It accepts `AgentDetails`, `UserDetails`, and `Request`, and returns the final
answer. It performs no environment access, SDK setup, or token acquisition.

### `samples/a365/s2s/s2s_exporter.py`

Becomes a thin executable entry point and owns:

- Export-result logging configuration.
- Loading `SampleConfig`.
- OpenTelemetry setup with the S2S resolver.
- Running the sample scenario.
- User-facing startup and completion output.

Running `python samples/a365/s2s/s2s_exporter.py` remains unchanged because
Python adds the script directory to the import path.

## Behavior and Errors

No runtime behavior changes are intended. Missing configuration still fails
before telemetry setup, mismatched tenant or agent values still return `None`
without invoking MSAL, and token acquisition errors remain visible on stdout.
The exporter logging, emitted Store-validation attributes, and S2S agentic-user
exclusions remain unchanged.

## Tests

The sample tests will load the focused modules explicitly:

- Configuration tests target `sample_config.py`.
- Resolver mismatch and cache tests target `token_resolver.py`.
- Scope and Store-contract tests target `sample_scenario.py`.
- Logging idempotence and orchestration tests target `s2s_exporter.py`.

Existing assertions for all five scopes, Store-required attributes, S2S identity
exclusions, resolver mismatches, token caching, and logging idempotence remain
in place.

Validation will include Black, Pylint, Mypy, the focused stale-tracer regression
sequence, and the pull request's GitHub Actions checks.

## Non-goals

- Creating a distributable Python package, adding `__init__.py`, or adding
  sample-local dependency manifests.
- Changing environment-variable names or authentication semantics.
- Splitting each telemetry scope into a separate module.
- Reproducing the .NET sample's dependency-injection, interface, and token
  result abstractions.
