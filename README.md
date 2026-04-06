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
from microsoft.opentelemetry import use_microsoft_opentelemetry

use_microsoft_opentelemetry(
	azure_monitor_connection_string="InstrumentationKey=...;IngestionEndpoint=...",
)
```

### Available Configuration Options

| Keyword argument | Type | Default | Description |
|---|---|---|---|
| `enable_azure_monitor` | `bool` | `True` | Enable Azure Monitor export. |
| `azure_monitor_connection_string` | `str` | `None` | Connection string for Application Insights. Also read from `APPLICATIONINSIGHTS_CONNECTION_STRING` env var. |
| `azure_monitor_exporter_credential` | `TokenCredential` | `None` | Azure AD token credential for authentication. |
| `azure_monitor_enable_live_metrics` | `bool` | `True` | Enable live metrics collection. |
| `azure_monitor_enable_performance_counters` | `bool` | `True` | Enable performance counter collection. |
| `azure_monitor_exporter_disable_offline_storage` | `bool` | `False` | Disable offline retry storage for failed telemetry. |
| `azure_monitor_exporter_storage_directory` | `str` | `None` | Custom directory for offline telemetry storage. |
| `azure_monitor_browser_sdk_loader_config` | `dict` | `None` | Browser SDK loader configuration. |
| `disable_logging` | `bool` | `False` | Disable the logging pipeline. |
| `disable_tracing` | `bool` | `False` | Disable the tracing pipeline. |
| `disable_metrics` | `bool` | `False` | Disable the metrics pipeline. |
| `resource` | `Resource` | auto | OpenTelemetry Resource. |
| `span_processors` | `list` | `[]` | Additional span processors. |
| `log_record_processors` | `list` | `[]` | Additional log record processors. |
| `metric_readers` | `list` | `[]` | Additional metric readers. |
| `views` | `list` | `[]` | Metric views. |
| `logger_name` | `str` | `None` | Logger name for log collection. |
| `logging_formatter` | `Formatter` | `None` | Formatter for collected logs. |
| `instrumentation_options` | `dict` | `None` | Per-library instrumentation enable/disable options. |
| `enable_trace_based_sampling_for_logs` | `bool` | `False` | Enable trace-based sampling for logs. |

### Sampling Configuration

Sampling is configured via standard OpenTelemetry environment variables:

| Environment variable | Description |
|---|---|
| `OTEL_TRACES_SAMPLER` | Sampler type to use (see supported values below). |
| `OTEL_TRACES_SAMPLER_ARG` | Argument for the sampler (e.g. sample ratio or traces per second). |

**Supported sampler values for `OTEL_TRACES_SAMPLER`:**

| Value | Description |
|---|---|
| `always_on` | Sample every trace. |
| `always_off` | Drop every trace. |
| `trace_id_ratio` | Sample a fixed percentage based on trace ID. Set ratio with `OTEL_TRACES_SAMPLER_ARG` (0–1). |
| `parentbased_always_on` | Parent-based, defaults to always on. |
| `parentbased_always_off` | Parent-based, defaults to always off. |
| `parentbased_trace_id_ratio` | Parent-based with trace ID ratio fallback. |
| `microsoft.fixed_percentage` | Azure Monitor fixed-percentage sampler. Set ratio with `OTEL_TRACES_SAMPLER_ARG` (0–1). |
| `microsoft.rate_limited` | Azure Monitor rate-limited sampler. Set target with `OTEL_TRACES_SAMPLER_ARG` (traces per second, default 5). |

**Example:**

```bash
export OTEL_TRACES_SAMPLER=trace_id_ratio
export OTEL_TRACES_SAMPLER_ARG=0.1
```

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

## Development

Create an environment and install the project with test dependencies:

```bash
pip install -e .[test]
pytest
```

## Reference

- POC repo: https://github.com/hectorhdzg/microsoft-opentelemetry-poc
- Planning document: [PLANNING.md](PLANNING.md)

## Repository Policies

- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [SUPPORT.md](SUPPORT.md)
- [PRIVACY.md](PRIVACY.md)
- [NOTICE.md](NOTICE.md)
- [LICENSE](LICENSE)
