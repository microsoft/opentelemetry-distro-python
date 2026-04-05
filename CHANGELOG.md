# Changelog

## 0.1.0b1 (Unreleased)

### Added

- Added `azure-monitor-opentelemetry` package source for Azure Monitor OpenTelemetry distro integration.
- Added `microsoft.opentelemetry` distro configuration with `use_microsoft_opentelemetry()` entry point for Azure Monitor.
- Added `enable_live_metrics` and `enable_performance_counters` kwargs passed directly to `configure_azure_monitor()`.

### Changed

- Renamed `enable_azure_monitor_export` kwarg to `disable_azure_monitor_exporter` to follow disable-by-default convention.
