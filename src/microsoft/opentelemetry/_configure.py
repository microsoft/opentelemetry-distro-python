# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
from logging import getLogger

from microsoft.opentelemetry._constants import (
    ENABLE_AZURE_MONITOR_ARG,
    _AZURE_MONITOR_KWARG_MAP,
)

_logger = getLogger(__name__)


def use_microsoft_opentelemetry(**kwargs) -> None:
    """Configure OpenTelemetry with Azure Monitor support.

    This function delegates to ``configure_azure_monitor()`` from the
    ``azure-monitor-opentelemetry`` package, which sets up the full
    Azure Monitor pipeline including tracing, logging, metrics, live
    metrics, performance counters, samplers, and instrumentations.
    All configuration defaults are handled by
    ``configure_azure_monitor()`` internally.

    :keyword bool enable_azure_monitor:
        Enable Azure Monitor export.
        Defaults to True when a connection string is available.
    :keyword str azure_monitor_connection_string:
        Connection string for Application Insights resource.
        Also read from ``APPLICATIONINSIGHTS_CONNECTION_STRING``
        env var by ``configure_azure_monitor()``.
    :keyword azure_monitor_exporter_credential:
        Azure AD token credential for authentication.
    :keyword bool azure_monitor_enable_live_metrics:
        Enable live metrics. Defaults to True.
    :keyword bool azure_monitor_enable_performance_counters:
        Enable performance counters. Defaults to True.
    :keyword bool azure_monitor_exporter_disable_offline_storage:
        Disable offline retry storage. Defaults to False.
    :keyword str azure_monitor_exporter_storage_directory:
        Custom directory for offline telemetry storage.
    :keyword dict azure_monitor_browser_sdk_loader_config:
        Browser SDK loader configuration.
    :keyword bool disable_logging:
        Disable the logging pipeline. Defaults to False.
    :keyword bool disable_tracing:
        Disable the tracing pipeline. Defaults to False.
    :keyword bool disable_metrics:
        Disable the metrics pipeline. Defaults to False.
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
    :rtype: None
    """
    enable_azure_monitor = kwargs.pop(ENABLE_AZURE_MONITOR_ARG, True)

    if not enable_azure_monitor:
        _logger.info("Azure Monitor exporter explicitly disabled.")
        return

    # Remap azure_monitor_ prefixed kwargs to internal names
    remapped = {}
    for key, value in kwargs.items():
        if key in _AZURE_MONITOR_KWARG_MAP:
            remapped[_AZURE_MONITOR_KWARG_MAP[key]] = value
        else:
            remapped[key] = value

    _setup_azure_monitor(**remapped)


def _setup_azure_monitor(**kwargs):
    """Delegate full Azure Monitor setup to azure-monitor-opentelemetry.

    All configuration defaults (resource, sampling, instrumentations,
    etc.) are handled by ``configure_azure_monitor()`` internally.
    """
    try:
        from microsoft.azureMonitor import configure_azure_monitor
    except ImportError:
        _logger.warning(
            "azure-monitor-opentelemetry dependencies not available. "
            "Install with: pip install microsoft-opentelemetry[azure-monitor]"
        )
        return

    try:
        configure_azure_monitor(**kwargs)
        _logger.info("Azure Monitor configured via azure-monitor-opentelemetry package")
    except Exception as ex:  # pylint: disable=broad-exception-caught
        _logger.warning(
            "Failed to configure Azure Monitor: %s",
            ex,
            exc_info=True,
        )
