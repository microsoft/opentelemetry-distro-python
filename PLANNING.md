# Planning

This document captures the minimum work needed to turn this repository into a working Python distribution for Microsoft OpenTelemetry based on the referenced POC.

## Target Outcome

Provide a Python package that exposes a single `configure_microsoft_opentelemetry()` entry point and can wire together:

- Azure Monitor export
- OTLP export
- Microsoft-specific exporter and span enrichment hooks
- optional GenAI instrumentations
- environment-variable based configuration

## Core Strategy: Extend Azure Monitor Distro

The team owns both this package and the Azure Monitor OpenTelemetry Distro (`azure-monitor-opentelemetry`). Instead of duplicating instrumentation and provider setup that Azure Monitor Distro already handles, this package will **extend** it.

Key principles:

- **No duplication of existing instrumentations.** Azure Monitor Distro already wires standard Python instrumentations (Flask, Django, FastAPI, requests, urllib, urllib3, psycopg2, etc.). This package should not re-implement that.
- **Upstream changes to Azure Monitor Distro.** The Azure Monitor Distro code needs to be updated to allow further customization — specifically, making the Azure Monitor exporter **not added by default** so that callers can control which exporters are attached.
- **Composition over reimplementation.** This package composes Azure Monitor Distro's provider and instrumentation setup with additional Microsoft-specific capabilities (OTLP export, GenAI instrumentations, agent observability extensions).
- **Thin layer on top.** The `configure_microsoft_opentelemetry()` function should delegate provider creation and standard instrumentation to Azure Monitor Distro, then layer on the extras.

### Required Changes to Azure Monitor Distro

- Add an option to skip automatic Azure Monitor exporter attachment (e.g., a flag or configuration mode that creates providers and instruments without binding the Azure Monitor exporter)
- Expose hooks or extension points for adding custom exporters, processors, or views after setup
- Ensure the instrumentation enablement logic can be reused without pulling in Azure Monitor-specific export

## Phase 1: Package Foundation

- ~~Finalize the published package name and import path~~ — **Decided: `microsoft-opentelemetry` on PyPI**
- Decide whether the public import should be `microsoft.opentelemetry` or a repo-local transitional name
- Supported Python versions follow the OpenTelemetry SDK/API supported versions — no independent decision needed
- Add package metadata, classifiers, and Python version constraints matching OpenTelemetry
- Add lint, format, and test tooling
- Add CI for unit tests and package validation

## Phase 2: Configuration Surface

- Define the `configure_microsoft_opentelemetry()` function signature
- Mirror the POC options that are core to the distro story
- Separate stable public options from experimental ones
- Add environment-variable parsing for all supported flags and endpoints
- Define validation and error messages for incompatible options

## Phase 3: Azure Monitor Distro Upstream Changes

- Add a configuration option to Azure Monitor Distro that skips automatic Azure Monitor exporter attachment
- Expose provider instances (TracerProvider, MeterProvider, LoggerProvider) after setup so callers can add exporters
- Ensure instrumentation enablement can be driven externally without importing Azure Monitor export dependencies
- Validate that the refactored Azure Monitor Distro still works identically for its existing users (no breaking changes)

## Phase 4: Core OpenTelemetry Setup (This Package)

- Delegate provider creation and standard instrumentation to Azure Monitor Distro
- When Azure Monitor export is requested, let Azure Monitor Distro attach its exporter normally
- When Azure Monitor export is not requested, use the new customization path to get providers without the exporter
- Add OTLP export for traces, logs, and metrics on top of the providers
- Add hooks for custom span processors, log processors, metric readers, and views
- Add sampling configuration support

## Phase 5: Additional Instrumentation (This Package Only)

- Add GenAI instrumentations sourced **only from OpenTelemetry contrib** packages:
  - OpenAI instrumentation from `opentelemetry-instrumentation-openai` (contrib)
  - OpenAI Agents SDK v2 instrumentation from `opentelemetry-instrumentation-openai-agents` (contrib)
  - LangChain instrumentation from OpenTelemetry contrib — **not yet published to PyPI**, include when available
- Do NOT include Traceloop instrumentations (these use the `opentelemetry` namespace but are not official OpenTelemetry contrib packages)
- Do NOT include Arize instrumentations as direct dependencies
- Add Microsoft-specific observability extensions for agent workloads
- Do NOT duplicate standard Python instrumentations already handled by Azure Monitor Distro
- Decide whether GenAI instrumentations are hard dependencies or optional extras
- Make instrumentation enablement explicit and debuggable

## Phase 6: External Instrumentation Normalization

- Define a normalization layer that can consume telemetry from third-party GenAI instrumentations (Traceloop, Arize, etc.) and align it to the expected semantic conventions
- Map external instrumentation span attributes and naming to OpenTelemetry GenAI semantic conventions
- Provide adapters or processors that normalize non-standard telemetry without taking a direct dependency on external instrumentation packages
- Document which external instrumentations are supported for normalization and any known gaps

## Phase 7: A365 Convergence

- Integrate the A365 exporter into the distro configuration surface
- Add custom span processors required by A365 agent observability scenarios
- Audit existing A365 instrumentations and determine which can be migrated to upstream OpenTelemetry contrib instrumentations
- For instrumentations that have OpenTelemetry equivalents, plan migration path and deprecation timeline
- For instrumentations with no upstream equivalent, keep as Microsoft-specific extensions and evaluate contributing them to OpenTelemetry
- Validate that existing A365 telemetry pipelines continue to work under the new distro setup

## Phase 8: Testing

- Unit tests for configuration parsing and defaults
- Unit tests for exporter and instrumentation enablement combinations
- Tests for environment-variable driven setup
- Tests for missing optional dependencies and graceful failures
- Smoke tests for the public import path and basic configuration call

## Phase 9: Documentation

- Add quick start examples for Azure Monitor only, OTLP only, and combined setups
- Document supported parameters and environment variables
- Document optional dependency groups if extras are used
- Document troubleshooting for missing dependencies and duplicate instrumentation
- Add migration guidance from manual OpenTelemetry setup

## Open Decisions

- Azure Monitor Distro customization API:
  Define the exact API surface for the upstream changes — flag-based (`skip_azure_monitor_exporter=True`), a factory function, or a builder pattern.
- Dependency strategy:
  Keep GenAI and Microsoft-specific instrumentations installed by default, or move to extras such as `openai`, `langchain`, `otlp-grpc`, and Microsoft-specific integrations. Standard web/HTTP instrumentations come from Azure Monitor Distro.
- Python version support:
  The POC notes broader distro support goals while the demo app required a newer Python version. This repo should define the actual supported range early.
- Import path:
  The POC examples use `from microsoft.opentelemetry import configure_microsoft_opentelemetry`, which may require namespace packaging decisions.
- Release strategy:
  The distro will need compatibility management across OpenTelemetry, Azure Monitor Distro, and Microsoft-specific packages. Coordinated releases may be needed when upstream Azure Monitor Distro changes land.
- Version coupling:
  Determine minimum Azure Monitor Distro version that includes the new customization hooks and pin accordingly.

## Suggested First Implementation Slice

Build the smallest useful version first:

1. Land the upstream changes in Azure Monitor Distro to support exporter-optional setup
2. Publish the intended import path for this package
3. Implement `configure_microsoft_opentelemetry()` delegating to Azure Monitor Distro
4. Support Azure Monitor (via distro default) and OTLP export (added by this package)
5. Add one GenAI instrumentation behind a flag
6. Add tests for the main enablement paths
7. Add README examples that match the implemented surface exactly
