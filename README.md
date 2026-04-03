# microsoft-opentelemetry-distro-python

## Repository Setup

The GitHub repository was provisioned with an onboarding placeholder that indicates repository setup and access control configuration may still need to be completed in the onboarding portal.

Until that setup is complete, some repository settings or access-management actions may remain restricted.

Python package for a Microsoft OpenTelemetry distribution that provides a single onboarding experience for observability across Azure Monitor, OTLP-compatible backends, and Microsoft Agent 365 style integrations.

This repository starts from the POC described in `hectorhdzg/microsoft-opentelemetry-poc`, but is intentionally kept minimal while the package shape and delivery plan are being defined.

## Goal

The target package should reduce fragmented setup across multiple observability stacks to one import and one configuration function.

Intended API shape:

```python
from microsoft.opentelemetry import configure_microsoft_opentelemetry

configure_microsoft_opentelemetry(
	azure_monitor_connection_string="InstrumentationKey=...;IngestionEndpoint=...",
)
```

### Available Configuration Options

| Keyword argument | Type | Default | Description |
|---|---|---|---|
| `azure_monitor_connection_string` | `str` | `None` | Connection string for Application Insights. Also read from `APPLICATIONINSIGHTS_CONNECTION_STRING` env var. |
| `disable_azure_monitor_exporter` | `bool` | `False` | Explicitly disable Azure Monitor export. |
| `credential` | `TokenCredential` | `None` | Azure AD token credential for authentication. |
| `disable_logging` | `bool` | `False` | Disable the logging pipeline. |
| `disable_tracing` | `bool` | `False` | Disable the tracing pipeline. |
| `disable_metrics` | `bool` | `False` | Disable the metrics pipeline. |
| `disable_live_metrics` | `bool` | `False` | Disable live metrics collection. |
| `disable_performance_counters` | `bool` | `False` | Disable performance counter collection. |
| `disable_offline_storage` | `bool` | `False` | Disable offline retry storage for failed telemetry. |
| `storage_directory` | `str` | `None` | Custom directory for offline telemetry storage. |
| `sampling_ratio` | `float` | `1.0` | Fixed-percentage sampling ratio (0–1). |
| `traces_per_second` | `float` | `5.0` | Rate-limited sampling target. |
| `sampler` | `str` | `None` | Sampler type name (e.g. `microsoft.rate_limited`). |
| `resource` | `Resource` | auto | OpenTelemetry Resource. |
| `span_processors` | `list` | `[]` | Additional span processors. |
| `log_record_processors` | `list` | `[]` | Additional log record processors. |
| `metric_readers` | `list` | `[]` | Additional metric readers. |
| `views` | `list` | `[]` | Metric views. |
| `logger_name` | `str` | `None` | Logger name for log collection. |
| `logging_formatter` | `Formatter` | `None` | Formatter for collected logs. |
| `instrumentation_options` | `dict` | `None` | Per-library instrumentation enable/disable options. |
| `enable_trace_based_sampling_for_logs` | `bool` | `False` | Enable trace-based sampling for logs. |
| `browser_sdk_loader_config` | `dict` | `None` | Browser SDK loader configuration. |

## Planned Scope

- Azure Monitor exporter support
- OTLP exporter support
- Microsoft-specific agent observability extensions
- GenAI instrumentation toggles for OpenAI, OpenAI Agents, and LangChain
- Standard Python web and HTTP instrumentations
- Environment-variable driven configuration
- A stable package surface for downstream agent applications

## Reference POC Highlights

The source POC positions the distro around three outcomes:

- one package, one API, one documentation surface
- less duplicated exporter and instrumentation wiring across teams
- much less application boilerplate compared with manual OpenTelemetry setup

The POC also describes this execution model:

1. Configure Azure Monitor when enabled
2. Otherwise create standalone OpenTelemetry providers
3. Attach OTLP exporters when requested
4. Attach Microsoft-specific exporters when requested
5. Enable standard instrumentations
6. Enable Microsoft-specific observability instrumentations
7. Enable GenAI contrib instrumentations

## Current Repository Layout

- `src/microsoft/opentelemetry/` distro package source
- `microsoft/tests/` distro unit and integration tests
- `tests/` smoke tests
- `azure-monitor-opentelemetry/` Azure Monitor OpenTelemetry source (vendored)
- `pyproject.toml` project metadata and dependencies
- `PLANNING.md` implementation plan and open questions

## Development

Create an environment and install the project with test dependencies:

```bash
pip install -e .[test]
pytest
```

## Reference

- POC repo: https://github.com/hectorhdzg/microsoft-opentelemetry-poc
- Planning document: [PLANNING.md](/c:/Repos/microsoft-opentelemetry-distro-python/PLANNING.md)

## Repository Policies

- [CODE_OF_CONDUCT.md](/c:/Repos/microsoft-opentelemetry-distro-python/CODE_OF_CONDUCT.md)
- [CONTRIBUTING.md](/c:/Repos/microsoft-opentelemetry-distro-python/CONTRIBUTING.md)
- [SECURITY.md](/c:/Repos/microsoft-opentelemetry-distro-python/SECURITY.md)
- [SUPPORT.md](/c:/Repos/microsoft-opentelemetry-distro-python/SUPPORT.md)
- [PRIVACY.md](/c:/Repos/microsoft-opentelemetry-distro-python/PRIVACY.md)
- [NOTICE.md](/c:/Repos/microsoft-opentelemetry-distro-python/NOTICE.md)
- [LICENSE](/c:/Repos/microsoft-opentelemetry-distro-python/LICENSE)
