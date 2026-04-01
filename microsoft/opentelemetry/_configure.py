# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
from logging import getLogger
from typing import Dict

from microsoft.opentelemetry._constants import (
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
    CONNECTION_STRING_ARG,
)
from microsoft.opentelemetry._types import ConfigurationValue
from microsoft.opentelemetry._utils.configurations import (
    _get_configurations,
)

_logger = getLogger(__name__)


# Keys that are specific to microsoft-opentelemetry and should not be
# forwarded to configure_azure_monitor()
_MICROSOFT_OTEL_ONLY_KEYS = frozenset({
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
})


def configure_microsoft_opentelemetry(**kwargs) -> None:
    """Configure OpenTelemetry with Azure Monitor support.

    This function delegates to ``configure_azure_monitor()`` from the
    ``azure-monitor-opentelemetry`` package, which sets up the full Azure Monitor
    pipeline including tracing, logging, metrics, live metrics, performance counters,
    samplers, and instrumentations.

    :keyword str azure_monitor_connection_string: Connection string for Application Insights resource.
    :keyword bool enable_live_metrics: Enable live metrics. Defaults to True.
    :keyword bool enable_performance_counters: Enable performance counters. Defaults to True.
    :keyword resource: OpenTelemetry Resource.
    :keyword list span_processors: Additional span processors.
    :keyword list log_record_processors: Additional log record processors.
    :keyword list metric_readers: Additional metric readers.
    :keyword list views: Metric views.
    :keyword float sampling_ratio: Fixed-percentage sampling ratio (0-1).
    :keyword float traces_per_second: Rate-limited sampling target.
    :keyword str logger_name: Logger name for log collection.
    :keyword logging_formatter: Formatter for collected logs.
    :rtype: None
    """
    configurations = _get_configurations(**kwargs)

    enable_azure_monitor = configurations.get(ENABLE_AZURE_MONITOR_EXPORTER_ARG, False)

    if enable_azure_monitor:
        _setup_azure_monitor(configurations)
    else:
        _logger.warning(
            "No azure_monitor_connection_string provided. "
            "Provide a connection string or set APPLICATIONINSIGHTS_CONNECTION_STRING env var."
        )


def _setup_azure_monitor(configurations: Dict[str, ConfigurationValue]):
    """Delegate full Azure Monitor setup to the azure-monitor-opentelemetry package."""
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        _logger.warning(
            "azure-monitor-opentelemetry package not installed. "
            "Install with: pip install azure-monitor-opentelemetry "
            "or: pip install microsoft-opentelemetry[azure-monitor]"
        )
        return

    # Build kwargs for configure_azure_monitor, excluding microsoft-otel-only keys
    # Remap azure_monitor_connection_string -> connection_string for upstream API
    azure_monitor_kwargs = {}
    for k, v in configurations.items():
        if k in _MICROSOFT_OTEL_ONLY_KEYS:
            continue
        if k == CONNECTION_STRING_ARG:
            azure_monitor_kwargs["connection_string"] = v
        else:
            azure_monitor_kwargs[k] = v

    try:
        configure_azure_monitor(**azure_monitor_kwargs)
        _logger.info("Azure Monitor configured via azure-monitor-opentelemetry package")
    except Exception as ex:
        _logger.warning("Failed to configure Azure Monitor: %s", ex)
