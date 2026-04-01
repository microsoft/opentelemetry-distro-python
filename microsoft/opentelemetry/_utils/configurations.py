# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

from logging import getLogger
from os import environ
from typing import Any, Dict

# Re-export shared configuration utilities from azure-monitor-opentelemetry.
# These functions handle base distro defaults and are called by _get_configurations().
from azure.monitor.opentelemetry._utils.configurations import (  # noqa: F401
    _default_disable_logging,
    _default_disable_metrics,
    _default_disable_tracing,
    _default_logger_name,
    _default_logging_formatter,
    _default_resource,
    _default_sampling_ratio,
    _default_instrumentation_options,
    _default_span_processors,
    _default_log_record_processors,
    _default_metric_readers,
    _default_enable_live_metrics,
    _default_enable_performance_counters,
    _default_views,
    _default_enable_trace_based_sampling,
    _default_browser_sdk_loader,
)

from microsoft.opentelemetry._constants import (
    CONNECTION_STRING_ARG,
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
    DISTRO_VERSION_ARG,
)
from microsoft.opentelemetry._types import ConfigurationValue
from microsoft.opentelemetry._version import VERSION


_logger = getLogger(__name__)


def _get_configurations(**kwargs) -> Dict[str, ConfigurationValue]:
    """Build the full configuration dictionary for the microsoft distro.

    Calls the shared azure-monitor-opentelemetry defaults for base settings,
    then applies microsoft-specific defaults for the connection string
    (uses 'azure_monitor_connection_string' instead of 'connection_string')
    and Azure Monitor exporter options.
    """
    configurations: Dict[str, Any] = {}

    for key, val in kwargs.items():
        configurations[key] = val
    configurations[DISTRO_VERSION_ARG] = VERSION

    # Shared defaults from azure-monitor-opentelemetry
    _default_disable_logging(configurations)
    _default_disable_metrics(configurations)
    _default_disable_tracing(configurations)
    # Microsoft-specific: uses CONNECTION_STRING_ARG = "azure_monitor_connection_string"
    _default_connection_string(configurations)
    _default_logger_name(configurations)
    _default_logging_formatter(configurations)
    _default_resource(configurations)
    _default_sampling_ratio(configurations)
    _default_instrumentation_options(configurations)
    _default_span_processors(configurations)
    _default_log_record_processors(configurations)
    _default_metric_readers(configurations)
    _default_enable_live_metrics(configurations)
    _default_enable_performance_counters(configurations)
    _default_views(configurations)
    _default_enable_trace_based_sampling(configurations)
    _default_browser_sdk_loader(configurations)
    # Microsoft-specific: Azure Monitor exporter defaults
    _default_exporter_options(configurations)

    return configurations


def _default_connection_string(configurations):
    """Set the connection string default for the microsoft distro.

    Uses 'azure_monitor_connection_string' as the key (not 'connection_string'),
    matching the microsoft distro's public API. The key is remapped to
    'connection_string' when delegating to configure_azure_monitor().
    """
    if CONNECTION_STRING_ARG in configurations:
        return
    env_connection_string = environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if env_connection_string is not None:
        configurations[CONNECTION_STRING_ARG] = env_connection_string


def _default_exporter_options(configurations):
    """Set default exporter options for Azure Monitor.

    Azure Monitor is enabled when an azure_monitor_connection_string is available
    (via parameter or APPLICATIONINSIGHTS_CONNECTION_STRING env var).
    """
    # Azure Monitor exporter: enable only when connection string is present
    has_connection_string = CONNECTION_STRING_ARG in configurations
    if ENABLE_AZURE_MONITOR_EXPORTER_ARG not in configurations:
        configurations[ENABLE_AZURE_MONITOR_EXPORTER_ARG] = has_connection_string
    elif configurations[ENABLE_AZURE_MONITOR_EXPORTER_ARG] and not has_connection_string:
        _logger.warning(
            "Azure Monitor exporter enabled but no azure_monitor_connection_string provided. "
            "Set azure_monitor_connection_string or APPLICATIONINSIGHTS_CONNECTION_STRING env var. "
            "Disabling Azure Monitor exporter."
        )
        configurations[ENABLE_AZURE_MONITOR_EXPORTER_ARG] = False

    if not configurations[ENABLE_AZURE_MONITOR_EXPORTER_ARG]:
        _logger.warning(
            "No exporters are enabled. Telemetry will be collected but not exported. "
            "Enable Azure Monitor by providing azure_monitor_connection_string."
        )
