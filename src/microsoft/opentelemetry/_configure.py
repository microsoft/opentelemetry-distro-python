# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
from logging import getLogger

from microsoft.opentelemetry._constants import (
    DISABLE_AZURE_MONITOR_EXPORTER_ARG,
)
from microsoft.opentelemetry._utils.configurations import (
    remap_disable_to_enable,
)

_logger = getLogger(__name__)


def configure_microsoft_opentelemetry(**kwargs) -> None:
    """Configure OpenTelemetry with Azure Monitor support.

    This function delegates to ``configure_azure_monitor()`` from the
    ``azure-monitor-opentelemetry`` package, which sets up the full
    Azure Monitor pipeline including tracing, logging, metrics, live
    metrics, performance counters, samplers, and instrumentations.
    All configuration defaults are handled by
    ``configure_azure_monitor()`` internally.

    :keyword str connection_string:
        Connection string for Application Insights resource.
        Also read from ``APPLICATIONINSIGHTS_CONNECTION_STRING``
        env var by ``configure_azure_monitor()``.
    :keyword bool disable_azure_monitor_exporter:
        Explicitly disable Azure Monitor export.
        Defaults to False when a connection string is available.
    :keyword credential:
        Azure AD token credential for authentication.
    :keyword bool disable_logging:
        Disable the logging pipeline. Defaults to False.
    :keyword bool disable_tracing:
        Disable the tracing pipeline. Defaults to False.
    :keyword bool disable_metrics:
        Disable the metrics pipeline. Defaults to False.
    :keyword bool disable_live_metrics:
        Disable live metrics. Defaults to False.
    :keyword bool disable_performance_counters:
        Disable performance counters. Defaults to False.
    :keyword bool disable_offline_storage:
        Disable offline retry storage. Defaults to False.
    :keyword str storage_directory:
        Custom directory for offline telemetry storage.
    :keyword resource: OpenTelemetry Resource.
    :keyword list span_processors: Additional span processors.
    :keyword list log_record_processors:
        Additional log record processors.
    :keyword list metric_readers: Additional metric readers.
    :keyword list views: Metric views.
    :keyword str logger_name: Logger name for log collection.
    :keyword logging_formatter: Formatter for collected logs.
    :keyword dict instrumentation_options:
        Per-library instrumentation enable/disable options.
    :keyword bool enable_trace_based_sampling_for_logs:
        Enable trace-based sampling for logs.
    :keyword dict browser_sdk_loader_config:
        Browser SDK loader configuration.
    :rtype: None
    """
    # Remap disable_* kwargs to enable_* for configure_azure_monitor()
    remap_disable_to_enable(kwargs, "disable_live_metrics", "enable_live_metrics")
    remap_disable_to_enable(
        kwargs,
        "disable_performance_counters",
        "enable_performance_counters",
    )

    # Determine whether Azure Monitor export should be disabled
    disable_azure_monitor_exporter = kwargs.pop(DISABLE_AZURE_MONITOR_EXPORTER_ARG, False)

    if disable_azure_monitor_exporter:
        _logger.info("Azure Monitor exporter explicitly disabled.")
        return

    _setup_azure_monitor(**kwargs)


def _setup_azure_monitor(**kwargs):
    """Delegate full Azure Monitor setup to azure-monitor-opentelemetry.

    All configuration defaults (resource, sampling, instrumentations,
    etc.) are handled by ``configure_azure_monitor()`` internally.
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
        configure_azure_monitor(**kwargs)
        msg = "Azure Monitor configured via azure-monitor-opentelemetry package"
        _logger.info(msg)
    except Exception as ex:  # pylint: disable=broad-exception-caught
        _logger.warning(
            "Failed to configure Azure Monitor: %s",
            ex,
            exc_info=True,
        )
