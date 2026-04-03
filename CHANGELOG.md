# Changelog

## 0.1.0b1 (Unreleased)

### Added

- Added `azure-monitor-opentelemetry` package source for Azure Monitor OpenTelemetry distro integration.
- Added `microsoft.opentelemetry` distro configuration with `configure_microsoft_opentelemetry()` entry point for Azure Monitor.
- Added `disable_live_metrics` and `disable_performance_counters` kwargs with automatic remapping to the `enable_*` form expected by `configure_azure_monitor()`.

### Changed

- Renamed `enable_azure_monitor_export` kwarg to `disable_azure_monitor_exporter` to follow disable-by-default convention.
