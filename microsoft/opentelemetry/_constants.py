# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

# Import shared constants from azure-monitor-opentelemetry to avoid duplication.
# The azure-monitor-opentelemetry package defines the base distro constants;
# this module re-exports them and adds microsoft-specific extensions.
from azure.monitor.opentelemetry._constants import (  # noqa: F401
    ENABLE_LIVE_METRICS_ARG,
    DISABLE_AZURE_CORE_TRACING_ARG,
    DISABLE_LOGGING_ARG,
    DISABLE_METRICS_ARG,
    DISABLE_TRACING_ARG,
    ENABLE_PERFORMANCE_COUNTERS_ARG,
    DISTRO_VERSION_ARG,
    LOGGER_NAME_ARG,
    LOGGING_FORMATTER_ARG,
    INSTRUMENTATION_OPTIONS_ARG,
    RESOURCE_ARG,
    SAMPLING_RATIO_ARG,
    SPAN_PROCESSORS_ARG,
    LOG_RECORD_PROCESSORS_ARG,
    METRIC_READERS_ARG,
    VIEWS_ARG,
    RATE_LIMITED_SAMPLER,
    FIXED_PERCENTAGE_SAMPLER,
    SAMPLING_TRACES_PER_SECOND_ARG,
    ENABLE_TRACE_BASED_SAMPLING_ARG,
    BROWSER_SDK_LOADER_CONFIG_ARG,
    SAMPLER_TYPE,
    SAMPLING_ARG,
    ALWAYS_ON_SAMPLER,
    ALWAYS_OFF_SAMPLER,
    TRACE_ID_RATIO_SAMPLER,
    PARENT_BASED_ALWAYS_ON_SAMPLER,
    PARENT_BASED_ALWAYS_OFF_SAMPLER,
    PARENT_BASED_TRACE_ID_RATIO_SAMPLER,
    SUPPORTED_OTEL_SAMPLERS,
    LOG_EXPORTER_NAMES_ARG,
    METRIC_EXPORTER_NAMES_ARG,
    SAMPLER_ARG,
    TRACE_EXPORTER_NAMES_ARG,
    LOGGER_NAME_ENV_ARG,
    LOGGING_FORMAT_ENV_ARG,
    _LOG_PATH_LINUX,
    _LOG_PATH_WINDOWS,
    _AZURE_SDK_INSTRUMENTATION_NAME,
    _FULLY_SUPPORTED_INSTRUMENTED_LIBRARIES,
    _PREVIEW_INSTRUMENTED_LIBRARIES,
    _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES,
    _AZURE_APP_SERVICE_RESOURCE_DETECTOR_NAME,
    _AZURE_VM_RESOURCE_DETECTOR_NAME,
)

# --------------------Microsoft Distro Overrides------------------------------------------

# The microsoft distro uses a different connection string parameter name
# to distinguish it from the azure-monitor-opentelemetry "connection_string" parameter.
# The microsoft distro remaps this to "connection_string" when delegating to configure_azure_monitor().
CONNECTION_STRING_ARG = "azure_monitor_connection_string"

_PREVIEW_ENTRY_POINT_WARNING = "Autoinstrumentation for the Microsoft OpenTelemetry Distro is in preview."

# Azure Monitor Exporter
ENABLE_AZURE_MONITOR_EXPORTER_ARG = "enable_azure_monitor_export"
