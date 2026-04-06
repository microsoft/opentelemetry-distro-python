# Changelog

## 0.1.0b1 (Unreleased)

### Added

- Added `azure-monitor-opentelemetry` package source for Azure Monitor OpenTelemetry distro integration.
- Added `microsoft.opentelemetry` distro configuration with `use_microsoft_opentelemetry()` entry point for Azure Monitor.
- Added `azure_monitor_enable_live_metrics` and `azure_monitor_enable_performance_counters` kwargs passed directly to `configure_azure_monitor()`.

### Changed

- Renamed `disable_azure_monitor_exporter` kwarg to `enable_azure_monitor` (inverted, defaults to True).
- Prefixed Azure Monitor-specific kwargs with `azure_monitor_` (e.g. `azure_monitor_connection_string`, `azure_monitor_exporter_credential`).
