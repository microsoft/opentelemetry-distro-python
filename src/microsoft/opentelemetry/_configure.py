# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
from logging import getLogger
from os import environ

from microsoft.opentelemetry._constants import (
    DISABLE_AZURE_MONITOR_EXPORTER_ARG,
    CONNECTION_STRING_ARG,
)
from microsoft.opentelemetry._utils.configurations import (
    remap_disable_to_enable,
)

_logger = getLogger(__name__)

_ENV_CONNECTION_STRING = "APPLICATIONINSIGHTS_CONNECTION_STRING"


def configure_microsoft_opentelemetry(**kwargs) -> None:
    """Configure OpenTelemetry with Azure Monitor support.

    This function delegates to ``configure_azure_monitor()`` from the
    ``azure-monitor-opentelemetry`` package, which sets up the full
    Azure Monitor pipeline including tracing, logging, metrics, live
    metrics, performance counters, samplers, and instrumentations.
    All configuration defaults are handled by
    ``configure_azure_monitor()`` internally.

    :keyword str azure_monitor_connection_string:
        Connection string for Application Insights resource.
    :keyword bool disable_azure_monitor_exporter:
        Explicitly disable Azure Monitor export.
        Defaults to False when a connection string is available.
    :keyword bool disable_live_metrics:
        Disable live metrics. Defaults to False.
    :keyword bool disable_performance_counters:
        Disable performance counters. Defaults to False.
    :keyword resource: OpenTelemetry Resource.
    :keyword list span_processors: Additional span processors.
    :keyword list log_record_processors:
        Additional log record processors.
    :keyword list metric_readers: Additional metric readers.
    :keyword list views: Metric views.
    :keyword float sampling_ratio:
        Fixed-percentage sampling ratio (0-1).
    :keyword float traces_per_second:
        Rate-limited sampling target.
    :keyword str logger_name: Logger name for log collection.
    :keyword logging_formatter: Formatter for collected logs.
    :rtype: None
    """
    # Resolve connection string from kwarg or env var
    connection_string = kwargs.pop(CONNECTION_STRING_ARG, None)
    if connection_string is None:
        connection_string = environ.get(_ENV_CONNECTION_STRING)

    # Remap disable_* kwargs to enable_* for configure_azure_monitor()
    remap_disable_to_enable(kwargs, "disable_live_metrics", "enable_live_metrics")
    remap_disable_to_enable(
        kwargs, "disable_performance_counters", "enable_performance_counters"
    )

    # Determine whether Azure Monitor export should be disabled
    disable_azure_monitor = kwargs.pop(DISABLE_AZURE_MONITOR_EXPORTER_ARG, None)
    explicitly_set = disable_azure_monitor is not None
    if disable_azure_monitor is None:
        disable_azure_monitor = connection_string is None
    elif not disable_azure_monitor and connection_string is None:
        _logger.warning(
            "Azure Monitor exporter enabled but no "
            "azure_monitor_connection_string provided. "
            "Set azure_monitor_connection_string or "
            "APPLICATIONINSIGHTS_CONNECTION_STRING env var. "
            "Disabling Azure Monitor exporter."
        )
        disable_azure_monitor = True

    if disable_azure_monitor:
        if explicitly_set:
            _logger.info("Azure Monitor exporter explicitly disabled.")
        else:
            _logger.info(
                "Azure Monitor exporter not configured. "
                "To enable, provide "
                "azure_monitor_connection_string or set "
                "APPLICATIONINSIGHTS_CONNECTION_STRING env var."
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
    except Exception as ex:  # pylint: disable=broad-exception-caught
        _logger.warning("Failed to configure Azure Monitor: %s", ex, exc_info=True)
