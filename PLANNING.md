# Planning

This document captures the minimum work needed to turn this repository into a working Python distribution for Microsoft OpenTelemetry based on the referenced POC.

## Target Outcome

Provide a Python package that exposes a single `configure_microsoft_opentelemetry()` entry point and can wire together:

- Azure Monitor export
- OTLP export
- Microsoft-specific exporter and span enrichment hooks
- optional GenAI instrumentations
- optional framework and client instrumentations
- environment-variable based configuration

## Phase 1: Package Foundation

- Finalize the published package name and import path
- Decide whether the public import should be `microsoft.opentelemetry` or a repo-local transitional name
- Add package metadata, supported Python versions, and classifiers
- Add lint, format, and test tooling
- Add CI for unit tests and package validation

## Phase 2: Configuration Surface

- Define the `configure_microsoft_opentelemetry()` function signature
- Mirror the POC options that are core to the distro story
- Separate stable public options from experimental ones
- Add environment-variable parsing for all supported flags and endpoints
- Define validation and error messages for incompatible options

## Phase 3: Core OpenTelemetry Setup

- Create or delegate `TracerProvider`, `MeterProvider`, and `LoggerProvider`
- Support the Azure Monitor path when Azure Monitor configuration is provided
- Support standalone provider creation when Azure Monitor is not enabled
- Add hooks for custom span processors, log processors, metric readers, and views
- Add sampling configuration support

## Phase 4: Exporters

- Integrate Azure Monitor export through the supported Azure Monitor package
- Integrate OTLP export for traces, logs, and metrics
- Define how Microsoft-specific export is plugged in
- Handle exporter-specific dependency availability clearly
- Ensure exporters can be enabled independently and together

## Phase 5: Instrumentation

- Add standard Python instrumentations such as FastAPI, Flask, Django, requests, urllib, urllib3, and psycopg2
- Add GenAI instrumentations for OpenAI, OpenAI Agents, and LangChain
- Add Microsoft-specific observability extensions for agent workloads
- Decide whether instrumentations are hard dependencies or optional extras
- Make instrumentation enablement explicit and debuggable

## Phase 6: Testing

- Unit tests for configuration parsing and defaults
- Unit tests for exporter and instrumentation enablement combinations
- Tests for environment-variable driven setup
- Tests for missing optional dependencies and graceful failures
- Smoke tests for the public import path and basic configuration call

## Phase 7: Documentation

- Add quick start examples for Azure Monitor only, OTLP only, and combined setups
- Document supported parameters and environment variables
- Document optional dependency groups if extras are used
- Document troubleshooting for missing dependencies and duplicate instrumentation
- Add migration guidance from manual OpenTelemetry setup

## Open Decisions

- Dependency strategy:
  Keep all instrumentations installed by default, or move to extras such as `fastapi`, `openai`, `langchain`, `otlp-grpc`, and Microsoft-specific integrations.
- Python version support:
  The POC notes broader distro support goals while the demo app required a newer Python version. This repo should define the actual supported range early.
- Import path:
  The POC examples use `from microsoft.opentelemetry import configure_microsoft_opentelemetry`, which may require namespace packaging decisions.
- Release strategy:
  The distro will need compatibility management across OpenTelemetry, Azure Monitor, and Microsoft-specific packages.

## Suggested First Implementation Slice

Build the smallest useful version first:

1. Publish the intended import path
2. Implement `configure_microsoft_opentelemetry()` with environment parsing
3. Support Azure Monitor and OTLP only
4. Add one or two standard instrumentations behind flags
5. Add tests for the main enablement paths
6. Add README examples that match the implemented surface exactly

## Reference Inputs

- POC repository: https://github.com/hectorhdzg/microsoft-opentelemetry-poc
- POC README describes the intended API, architecture, and parameter surface
- POC considerations document highlights dependency size, feature gating, versioning, and multi-language concerns