# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
from logging import getLogger
from os import environ

from microsoft.opentelemetry._constants import (
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
    CONNECTION_STRING_ARG,
)

_logger = getLogger(__name__)

_ENV_CONNECTION_STRING = "APPLICATIONINSIGHTS_CONNECTION_STRING"


def configure_microsoft_opentelemetry(**kwargs) -> None:
    """Configure OpenTelemetry with Azure Monitor support.

    This function delegates to ``configure_azure_monitor()`` from the
    ``azure-monitor-opentelemetry`` package, which sets up the full Azure Monitor
    pipeline including tracing, logging, metrics, live metrics, performance counters,
    samplers, and instrumentations.  All configuration defaults are handled by
    ``configure_azure_monitor()`` internally.

    :keyword str azure_monitor_connection_string: Connection string for Application Insights resource.
    :keyword bool enable_azure_monitor_export: Explicitly enable/disable Azure Monitor.
        Defaults to True when a connection string is available.
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
    # Resolve connection string from kwarg or env var
    connection_string = kwargs.pop(CONNECTION_STRING_ARG, None)
    if connection_string is None:
        connection_string = environ.get(_ENV_CONNECTION_STRING)

    # Determine whether Azure Monitor export should be enabled
    enable_azure_monitor = kwargs.pop(ENABLE_AZURE_MONITOR_EXPORTER_ARG, None)
    if enable_azure_monitor is None:
        enable_azure_monitor = connection_string is not None
    elif enable_azure_monitor and connection_string is None:
        _logger.warning(
            "Azure Monitor exporter enabled but no azure_monitor_connection_string provided. "
            "Set azure_monitor_connection_string or APPLICATIONINSIGHTS_CONNECTION_STRING env var. "
            "Disabling Azure Monitor exporter."
        )
        enable_azure_monitor = False

    if not enable_azure_monitor:
        _logger.warning(
            "No azure_monitor_connection_string provided. "
            "Provide a connection string or set APPLICATIONINSIGHTS_CONNECTION_STRING env var."
        )
        return

    _setup_azure_monitor(connection_string=connection_string, **kwargs)


def _setup_azure_monitor(connection_string, **kwargs):
    """Delegate full Azure Monitor setup to the azure-monitor-opentelemetry package.

    All configuration defaults (resource, sampling, instrumentations, etc.)
    are handled by ``configure_azure_monitor()`` internally.
    """
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        _logger.warning(
            "azure-monitor-opentelemetry package not installed. "
            "Install with: pip install azure-monitor-opentelemetry "
            "or: pip install microsoft-opentelemetry[azure-monitor]"
        )
        return

    try:
        configure_azure_monitor(connection_string=connection_string, **kwargs)
        _logger.info("Azure Monitor configured via azure-monitor-opentelemetry package")
    except Exception as ex:
        _logger.warning("Failed to configure Azure Monitor: %s", ex)
