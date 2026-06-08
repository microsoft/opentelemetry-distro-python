# Release History

## Unreleased

### Bugs Fixed
- Flatten LangChain/LangGraph multi-part message ``content`` into a plain
  ``TextPart.content`` string so ``gen_ai.output.messages`` no longer contains
  a Python-``repr`` blob on ``invoke_agent`` wrapper spans
  ([#189](https://github.com/microsoft/opentelemetry-distro-python/issues/189))

# 1.3.2 (2026-05-29)

### Bugs Fixed
- Add an explicit `get_span_context` override on `EnrichedReadableSpan`
  ([#180](https://github.com/microsoft/opentelemetry-distro-python/pull/180))

### Other Changes
- Add GitHub Actions workflow for the `needs-author-feedback` label
  ([#178](https://github.com/microsoft/opentelemetry-distro-python/pull/178))

# 1.3.1 (2026-05-28)

### Features Added
- Add `ApplyGuardrailScope` for security guardrail evaluations
  ([#173](https://github.com/microsoft/opentelemetry-distro-python/pull/173))

### Bugs Fixed
- Fix `enable_sensitive_data` leaking to all instrumentors
  ([#176](https://github.com/microsoft/opentelemetry-distro-python/pull/176))
- Fix LangChain tracer main-agent attribute propagation timing
  ([#171](https://github.com/microsoft/opentelemetry-distro-python/pull/171))

### Other Changes
- Invoke-agent wrapper span now populates tool-call turns and `gen_ai.tool.definitions`
  ([#174](https://github.com/microsoft/opentelemetry-distro-python/pull/174))
- Add wheel build and artifact upload to PR validation
  ([#177](https://github.com/microsoft/opentelemetry-distro-python/pull/177))
- Add setter functions for feature and instrumentation bits
  ([#157](https://github.com/microsoft/opentelemetry-distro-python/pull/157))

## 1.3.0 (2026-05-27)

### Features Added
- Add circuit breaker to A365 exporter to prevent silent telemetry loss
  ([#153](https://github.com/microsoft/opentelemetry-distro-python/pull/153))
- Add token usage extraction for LangChain tracer
  ([#161](https://github.com/microsoft/opentelemetry-distro-python/pull/161))
- Add more GenAI attributes to LangChain tracer
  ([#156](https://github.com/microsoft/opentelemetry-distro-python/pull/156))
- Align message format to OTel spec: remove version envelope
  ([#162](https://github.com/microsoft/opentelemetry-distro-python/pull/162))

### Bugs Fixed
- Use `get_span_context()` instead of `.context` to support `NonRecordingSpan`
  ([#168](https://github.com/microsoft/opentelemetry-distro-python/pull/168))
- Use standard `gen_ai.conversation.id` instead of `microsoft.sessionid` in LangChain tracer
  ([#152](https://github.com/microsoft/opentelemetry-distro-python/pull/152))
- Emit OTel-spec structured messages on `invoke_agent` spans
  ([#164](https://github.com/microsoft/opentelemetry-distro-python/pull/164))
- Prevent OOM from unbounded dicts in LangChain tracer
  ([#154](https://github.com/microsoft/opentelemetry-distro-python/pull/154))
- Bump `agent-framework>=1.4.0` to resolve dependency conflict
  ([#155](https://github.com/microsoft/opentelemetry-distro-python/pull/155))
- Add 30s timeout to FIC token resolver MSAL calls
  ([#150](https://github.com/microsoft/opentelemetry-distro-python/pull/150))

### Other Changes
- Add project URLs to PyPI and fix broken relative links
  ([#169](https://github.com/microsoft/opentelemetry-distro-python/pull/169))
- Add pytest-benchmark suite and PR regression gate
  ([#165](https://github.com/microsoft/opentelemetry-distro-python/pull/165))
- Bump `mem0ai` from 1.0.11 to 2.0.0b2
  ([#163](https://github.com/microsoft/opentelemetry-distro-python/pull/163))

## 1.2.0 (2026-05-18)

### Features Added
- Forward `instrumentation_options` kwargs to instrumentors
  ([#149](https://github.com/microsoft/opentelemetry-distro-python/pull/149))
- Add A365-specific OpenAI Agents SDK instrumentor (`A365OpenAIAgentsInstrumentor`). When `enable_a365=True`, the distro uses this bundled instrumentor instead of the upstream `opentelemetry-instrumentation-openai-agents-v2`, producing spans with the A365 versioned envelope format, `custom.parent.span.id`, per-message indexed attributes, detailed token counts, and `graph_node_parent_id` for handoffs.
  ([#132](https://github.com/microsoft/opentelemetry-distro-python/pull/132))

### Bugs Fixed
- Fix duplicate chat spans and HTTP spans not propagating in LangChain
  ([#147](https://github.com/microsoft/opentelemetry-distro-python/pull/147))
- Revert: Fix `get_caller_pairs` userId fallback
  ([#141](https://github.com/microsoft/opentelemetry-distro-python/pull/141))
- Capitalize env var to avoid case-sensitive conflicts
  ([#137](https://github.com/microsoft/opentelemetry-distro-python/pull/137))
- Add product context fallback for subchannels
  ([#129](https://github.com/microsoft/opentelemetry-distro-python/pull/129))

### Other Changes
- Port Agent365 integration tests using real distro pipeline
  ([#146](https://github.com/microsoft/opentelemetry-distro-python/pull/146))
- Make `microsoft-agents-hosting-core` and `microsoft-agents-activity` optional dependencies
  ([#117](https://github.com/microsoft/opentelemetry-distro-python/pull/117))
- Pin genai util
  ([#145](https://github.com/microsoft/opentelemetry-distro-python/pull/145))
- Update telemetry SDK name to `microsoft-opentelemetry`
  ([#138](https://github.com/microsoft/opentelemetry-distro-python/pull/138))
- Update azure monitor exporter minimum version
  ([#136](https://github.com/microsoft/opentelemetry-distro-python/pull/136))

## 1.1.0 (2026-05-11)

### Features Added
- Add GenAI main-agent attribution processors
  ([#120](https://github.com/microsoft/opentelemetry-distro-python/pull/120))
- Add `enable_sensitive_data` parameter to configure sensitive data in Agent Framework
  ([#121](https://github.com/microsoft/opentelemetry-distro-python/pull/121))

### Bugs Fixed
- Fix `get_caller_pairs` to resolve `userId` across all channels
  ([#118](https://github.com/microsoft/opentelemetry-distro-python/pull/118))
- Fix response model not being set when using LangChain
  ([#116](https://github.com/microsoft/opentelemetry-distro-python/pull/116))

### Other Changes
- Add Agent Framework sample
  ([#122](https://github.com/microsoft/opentelemetry-distro-python/pull/122))
- Add auth scopes breaking change to A365 migration guide
  ([#123](https://github.com/microsoft/opentelemetry-distro-python/pull/123))
- Fix MIGRATION_A365.md documentation errors
  ([#109](https://github.com/microsoft/opentelemetry-distro-python/pull/109))
- Add issues template and notification actions
  ([#112](https://github.com/microsoft/opentelemetry-distro-python/pull/112))
- Promote new A365 owners
  ([#125](https://github.com/microsoft/opentelemetry-distro-python/pull/125))
- Add troubleshooting sections and duplicate spans guide
  ([#115](https://github.com/microsoft/opentelemetry-distro-python/pull/115))
- Drop support for Python 3.9.
  ([#110](https://github.com/microsoft/opentelemetry-distro-python/pull/110))
- Add Fabric/ADX getting started guide and sample.
  ([#104](https://github.com/microsoft/opentelemetry-distro-python/pull/104))
- Update A365 documentation and links.
  ([#101](https://github.com/microsoft/opentelemetry-distro-python/pull/101))
- Fix CODEOWNERS sub-owners.
  ([#103](https://github.com/microsoft/opentelemetry-distro-python/pull/103))

## 1.0.0 (2026-04-30)

### Features Added
- GA release of the Microsoft OpenTelemetry Distro for Python
- `use_microsoft_opentelemetry()` entry point for unified telemetry configuration
- Azure Monitor export with connection-string-based configuration
- OTLP export for traces, metrics, and logs
- A365 observability exporter with baggage propagation and scope override support
- GenAI instrumentations: OpenAI v2, OpenAI Agents SDK v2, LangChain (internal), Semantic Kernel, Microsoft Agent Framework
- Console exporter for local development and debugging
- SDK self-telemetry (sdkstats) for health and usage diagnostics
- Auto-instrumentation support via OpenTelemetry distro entry point
- Standard web-framework instrumentations (Django, FastAPI, Flask, httpx, requests, urllib, urllib3, psycopg2)
- Environment-variable-based configuration for all supported options
- Spectra Collector sidecar support with graceful fallback
- Browser SDK Loader integration for Azure Monitor
- Configurable instrumentation enablement via `instrumentation_options`
- Add documentation to include span filtering for console exporter traces

### Breaking Changes
- Package name is `microsoft-opentelemetry` (replaces all pre-release versions)
- `enable_azure_monitor` is off by default
- `tenant_id` and `agent_id` removed from configuration options
- Web-framework/HTTP-client instrumentations disabled by default when A365 is enabled; GenAI instrumentations remain enabled

## 0.1.0b3 (2026-04-29)

### Features Added
- Add configuration options for the `ENABLE_A365_OBSERVABILITY_EXPORTER` and `A365_OBSERVABILITY_SCOPE_OVERRIDE` environment variables
  ([#87](https://github.com/microsoft/opentelemetry-distro-python/pull/87))

### Bugs Fixed
- Reverted [#81](https://github.com/microsoft/opentelemetry-distro-python/pull/81): baggage propagation now requires `enable_a365=True` and respects `ENABLE_A365_OBSERVABILITY_EXPORTER` as before.
  ([#85](https://github.com/microsoft/opentelemetry-distro-python/pull/85))

### Other Changes
- Make `langchain-core` an optional dependency. The LangChain instrumentation
  is now installable via `pip install microsoft-opentelemetry[langchain]` and
  fails silently with a one-time warning when `langchain-core` is not
  installed.
  ([#80](https://github.com/microsoft/opentelemetry-distro-python/pull/80))


## 0.1.0b2 (2026-04-28)

### Bugs Fixed
- Ensure baggage properties propagate to child spans for all exporters
  ([#81](https://github.com/microsoft/opentelemetry-distro-python/pull/81))


## 0.1.0b1 (2026-04-27)

### Features Added

- Ensure baggage properties propagate to child spans when the console exporter is chosen and A365 exporter is disabled
  ([#74](https://github.com/microsoft/opentelemetry-distro-python/pull/74))
- Disable web-framework / HTTP-client instrumentations
  (`django`, `fastapi`, `flask`, `httpx`, `psycopg2`, `requests`, `urllib`, `urllib3`,
  `azure_sdk`) by default when A365 is enabled. GenAI instrumentations
  (`langchain`, `openai`, `openai_agents`, `semantic_kernel`,
  `agent_framework`) remain enabled. Users can override either default via
  `instrumentation_options`.
  ([#64](https://github.com/microsoft/opentelemetry-distro-python/pull/64))

### Bugs Fixed

- Fetch the distro version instead of the upstream core package
  ([#73](https://github.com/microsoft/opentelemetry-distro-python/pull/73))

## 0.1.0a4 (2026-04-24)

### Breaking Changes

- Remove tenant_id, agent_id from config options
  ([#59](https://github.com/microsoft/opentelemetry-distro-python/pull/59))

### Features Added

- `enable_azure_monitor` is off by default
  ([#60](https://github.com/microsoft/opentelemetry-distro-python/pull/60))
- Match Upstream Changes: Update scope value to support new exporter path
  ([#62](https://github.com/microsoft/opentelemetry-distro-python/pull/62))

## 0.1.0a3 (2026-04-22)

### Features Added

- Vendor A365 core observability code
  ([#47](https://github.com/microsoft/opentelemetry-distro-python/pull/47))
- Add agent framework and semantic kernel instrumentations
  ([#50](https://github.com/microsoft/opentelemetry-distro-python/pull/50))
- Add Spectra Collector sidecar support with graceful fallback
  ([#48](https://github.com/microsoft/opentelemetry-distro-python/pull/48))
- Add console exporter for traces, metrics, and logs
  ([#54](https://github.com/microsoft/opentelemetry-distro-python/pull/54))

## 0.1.0a2 (2026-04-20)

### Features Added

- Integrate A365 observability into distro
  ([#45](https://github.com/microsoft/opentelemetry-distro-python/pull/45))
- Support openai-v2 and openai-agents-v2
  ([#37](https://github.com/microsoft/opentelemetry-distro-python/pull/37))

### Other Changes

- Modify the logic to add providers when azure monitor config is disabled
  ([#24](https://github.com/microsoft/opentelemetry-distro-python/pull/24))


## 0.1.0a1 (2026-04-10)

### Features Added

- Add langchain instrumentation 
  ([#26](https://github.com/microsoft/opentelemetry-distro-python/pull/26))
- Add Microsoft Opentelemetry Distro Configuration
  ([#9](https://github.com/microsoft/opentelemetry-distro-python/pull/9))
- Add langchain samples
  ([#8](https://github.com/microsoft/opentelemetry-distro-python/pull/8))
- Add azure-monitor-opentelemetry distro source
  ([#7](https://github.com/microsoft/opentelemetry-distro-python/pull/7))
- Added `azure-monitor-opentelemetry` package source for Azure Monitor OpenTelemetry distro integration.
  ([#7](https://github.com/microsoft/opentelemetry-distro-python/pull/7))

### Other Changes

- Add support for local mypy, pylint, black checks
  ([#14](https://github.com/microsoft/opentelemetry-distro-python/pull/14))
- Add mypy and pyright checks
  ([#15](https://github.com/microsoft/opentelemetry-distro-python/pull/15))
- Fix lint and format on langchain samples
  ([#16](https://github.com/microsoft/opentelemetry-distro-python/pull/16))
- Update max length to 120
  ([#17](https://github.com/microsoft/opentelemetry-distro-python/pull/17))
- Add environment variables to README
  ([#12](https://github.com/microsoft/opentelemetry-distro-python/pull/12))
- Add PR build
  ([#10](https://github.com/microsoft/opentelemetry-distro-python/pull/10))
- Microsoft mandatory file
  ([#2](https://github.com/microsoft/opentelemetry-distro-python/pull/2))

