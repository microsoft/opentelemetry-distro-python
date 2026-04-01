# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

from logging import getLogger
from os import environ
from typing import Any, Dict

# Re-export shared configuration utilities from azure-monitor-opentelemetry.
# These functions handle base distro defaults (logging, metrics, tracing,
# sampling, instrumentations, etc.) and are identical between the two packages.
from azure.monitor.opentelemetry._utils.configurations import (  # noqa: F401
    _is_instrumentation_enabled,
    _get_sampler_from_name,
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
    ENABLE_OTLP_EXPORTER_ARG,
    OTLP_ENDPOINT_ARG,
    OTLP_PROTOCOL_ARG,
    OTLP_HEADERS_ARG,
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
    ENABLE_A365_EXPORTER_ARG,
    A365_TOKEN_RESOLVER_ARG,
    A365_CLUSTER_CATEGORY_ARG,
    A365_EXPORTER_OPTIONS_ARG,
    ENABLE_A365_OPENAI_INSTRUMENTATION_ARG,
    ENABLE_A365_LANGCHAIN_INSTRUMENTATION_ARG,
    ENABLE_A365_SEMANTICKERNEL_INSTRUMENTATION_ARG,
    ENABLE_A365_AGENTFRAMEWORK_INSTRUMENTATION_ARG,
    ENABLE_GENAI_OPENAI_INSTRUMENTATION_ARG,
    ENABLE_GENAI_OPENAI_AGENTS_INSTRUMENTATION_ARG,
    ENABLE_GENAI_LANGCHAIN_INSTRUMENTATION_ARG,
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
    and exporter options (OTLP, A365, GenAI).
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
    # Microsoft-specific: OTLP, Azure Monitor, A365, GenAI exporter/instrumentation defaults
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
    """Set default exporter options for OTLP, Azure Monitor, and A365.

    Azure Monitor is only enabled when an azure_monitor_connection_string is available
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

    # OTLP exporter: check environment variable or kwarg
    if ENABLE_OTLP_EXPORTER_ARG not in configurations:
        configurations[ENABLE_OTLP_EXPORTER_ARG] = (
            environ.get("ENABLE_OTLP_EXPORTER", "").lower() == "true"
        )
    configurations.setdefault(OTLP_ENDPOINT_ARG, environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    configurations.setdefault(OTLP_PROTOCOL_ARG, environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"))
    configurations.setdefault(OTLP_HEADERS_ARG, environ.get("OTEL_EXPORTER_OTLP_HEADERS"))

    # A365 exporter: auto-enable when a365_token_resolver is provided or
    # when ENABLE_A365_EXPORTER=true env var is set
    has_a365_token_resolver = A365_TOKEN_RESOLVER_ARG in configurations and configurations[A365_TOKEN_RESOLVER_ARG] is not None
    if ENABLE_A365_EXPORTER_ARG not in configurations:
        configurations[ENABLE_A365_EXPORTER_ARG] = (
            has_a365_token_resolver
            or environ.get("ENABLE_A365_EXPORTER", "").lower() == "true"
        )
    configurations.setdefault(A365_TOKEN_RESOLVER_ARG, None)
    configurations.setdefault(A365_CLUSTER_CATEGORY_ARG, environ.get("A365_CLUSTER_CATEGORY", "prod"))
    configurations.setdefault(A365_EXPORTER_OPTIONS_ARG, None)

    # A365 instrumentations: check environment variables or kwargs
    if ENABLE_A365_OPENAI_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_A365_OPENAI_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_A365_OPENAI_INSTRUMENTATION", "").lower() == "true"
        )
    if ENABLE_A365_LANGCHAIN_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_A365_LANGCHAIN_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_A365_LANGCHAIN_INSTRUMENTATION", "").lower() == "true"
        )
    if ENABLE_A365_SEMANTICKERNEL_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_A365_SEMANTICKERNEL_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_A365_SEMANTICKERNEL_INSTRUMENTATION", "").lower() == "true"
        )
    if ENABLE_A365_AGENTFRAMEWORK_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_A365_AGENTFRAMEWORK_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_A365_AGENTFRAMEWORK_INSTRUMENTATION", "").lower() == "true"
        )

    # GenAI OTel contrib instrumentations: check environment variables or kwargs
    if ENABLE_GENAI_OPENAI_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_GENAI_OPENAI_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_GENAI_OPENAI_INSTRUMENTATION", "").lower() == "true"
        )
    if ENABLE_GENAI_OPENAI_AGENTS_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_GENAI_OPENAI_AGENTS_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_GENAI_OPENAI_AGENTS_INSTRUMENTATION", "").lower() == "true"
        )
    if ENABLE_GENAI_LANGCHAIN_INSTRUMENTATION_ARG not in configurations:
        configurations[ENABLE_GENAI_LANGCHAIN_INSTRUMENTATION_ARG] = (
            environ.get("ENABLE_GENAI_LANGCHAIN_INSTRUMENTATION", "").lower() == "true"
        )

    # Warn if no exporters are enabled at all
    if (
        not configurations[ENABLE_AZURE_MONITOR_EXPORTER_ARG]
        and not configurations[ENABLE_OTLP_EXPORTER_ARG]
        and not configurations[ENABLE_A365_EXPORTER_ARG]
    ):
        _logger.warning(
            "No exporters are enabled. Telemetry will be collected but not exported. "
            "Enable at least one exporter: Azure Monitor (azure_monitor_connection_string), "
            "OTLP (enable_otlp_export=True), or A365 (enable_a365_export=True)."
        )
