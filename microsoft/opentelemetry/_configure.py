# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
from functools import cached_property
from logging import getLogger, Formatter
from typing import Any, Dict, List, Optional, cast

from opentelemetry.metrics import get_meter_provider, set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import get_tracer_provider, set_tracer_provider
from opentelemetry.util._importlib_metadata import (
    EntryPoint,
    distributions,
    entry_points,
)

from microsoft.opentelemetry._constants import (
    _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES,
    _AZURE_SDK_INSTRUMENTATION_NAME,
    DISABLE_LOGGING_ARG,
    DISABLE_METRICS_ARG,
    DISABLE_TRACING_ARG,
    ENABLE_LIVE_METRICS_ARG,
    ENABLE_PERFORMANCE_COUNTERS_ARG,
    LOGGER_NAME_ARG,
    LOGGING_FORMATTER_ARG,
    RESOURCE_ARG,
    SAMPLING_RATIO_ARG,
    SAMPLING_TRACES_PER_SECOND_ARG,
    SPAN_PROCESSORS_ARG,
    LOG_RECORD_PROCESSORS_ARG,
    METRIC_READERS_ARG,
    VIEWS_ARG,
    ENABLE_TRACE_BASED_SAMPLING_ARG,
    SAMPLING_ARG,
    SAMPLER_TYPE,
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
    CONNECTION_STRING_ARG,
)
from microsoft.opentelemetry._types import ConfigurationValue
from microsoft.opentelemetry._utils.configurations import (
    _get_configurations,
    _is_instrumentation_enabled,
    _get_sampler_from_name,
)
from microsoft.opentelemetry._utils.instrumentation import (
    get_dist_dependency_conflicts,
)

_logger = getLogger(__name__)


# Keys that are specific to microsoft-opentelemetry and should not be
# forwarded to configure_azure_monitor()
_MICROSOFT_OTEL_ONLY_KEYS = frozenset({
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
})


def configure_microsoft_opentelemetry(**kwargs) -> None:
    """Configure OpenTelemetry with Azure Monitor support.

    This function sets up OpenTelemetry pipelines for tracing, logging, and metrics.

    When Azure Monitor is enabled, this function delegates to ``configure_azure_monitor()``
    from the ``azure-monitor-opentelemetry`` package, which sets up the full Azure Monitor
    pipeline including live metrics, performance counters, browser SDK loader, samplers,
    and instrumentations.

    When Azure Monitor is disabled, this function creates its own OpenTelemetry providers
    and sets up instrumentations.

    :keyword str azure_monitor_connection_string: Connection string for Application Insights resource.
    :keyword bool enable_azure_monitor_export: Enable Azure Monitor exporter.
        Auto-enabled when azure_monitor_connection_string is provided.
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

    # --- Step 1: If Azure Monitor is enabled, delegate to configure_azure_monitor() ---
    if enable_azure_monitor:
        _setup_azure_monitor(configurations)

    # --- Step 2: If Azure Monitor is NOT enabled, set up standalone OTel providers ---
    if not enable_azure_monitor:
        _setup_standalone_providers(configurations)

    # --- Step 3: If no Azure Monitor, set up instrumentations ourselves ---
    # (configure_azure_monitor already handles instrumentations when enabled)
    if not enable_azure_monitor:
        _setup_instrumentations(configurations)


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


def _setup_standalone_providers(configurations: Dict[str, ConfigurationValue]):
    """Set up OTel providers when Azure Monitor is not enabled."""
    disable_tracing = configurations[DISABLE_TRACING_ARG]
    disable_logging = configurations[DISABLE_LOGGING_ARG]
    disable_metrics = configurations[DISABLE_METRICS_ARG]

    if not disable_tracing:
        _setup_standalone_tracing(configurations)

    if not disable_logging:
        _setup_standalone_logging(configurations)

    if not disable_metrics:
        _setup_standalone_metrics(configurations)


def _setup_standalone_tracing(configurations: Dict[str, ConfigurationValue]):
    """Create a TracerProvider when Azure Monitor is not handling it."""
    resource: Resource = configurations[RESOURCE_ARG]  # type: ignore

    if SAMPLING_ARG in configurations:
        sampler_arg = configurations[SAMPLING_ARG]
        sampler_type = configurations[SAMPLER_TYPE]
        sampler = _get_sampler_from_name(sampler_type, sampler_arg)
        tracer_provider = TracerProvider(sampler=sampler, resource=resource)
    elif SAMPLING_RATIO_ARG in configurations:
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        tracer_provider = TracerProvider(
            sampler=TraceIdRatioBased(cast(float, configurations[SAMPLING_RATIO_ARG])),
            resource=resource,
        )
    else:
        tracer_provider = TracerProvider(resource=resource)

    for span_processor in configurations[SPAN_PROCESSORS_ARG]:  # type: ignore
        tracer_provider.add_span_processor(span_processor)  # type: ignore

    set_tracer_provider(tracer_provider)


def _setup_standalone_logging(configurations: Dict[str, ConfigurationValue]):
    """Create a LoggerProvider when Azure Monitor is not handling it."""
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler

        resource: Resource = configurations[RESOURCE_ARG]  # type: ignore
        logger_provider = LoggerProvider(resource=resource)

        for custom_processor in configurations[LOG_RECORD_PROCESSORS_ARG]:  # type: ignore
            logger_provider.add_log_record_processor(custom_processor)  # type: ignore

        set_logger_provider(logger_provider)

        # Set up logging handler
        logger_name: str = configurations[LOGGER_NAME_ARG]  # type: ignore
        logging_formatter: Optional[Formatter] = configurations.get(LOGGING_FORMATTER_ARG)  # type: ignore
        logger = getLogger(logger_name)
        if not any(isinstance(handler, LoggingHandler) for handler in logger.handlers):
            handler = LoggingHandler(logger_provider=logger_provider)
            if logging_formatter:
                try:
                    handler.setFormatter(logging_formatter)
                except Exception as ex:
                    _logger.warning("Failed to set logging formatter: %s", ex)
            logger.addHandler(handler)

        # Setup Events
        try:
            from opentelemetry._events import _set_event_logger_provider
            from opentelemetry.sdk._events import EventLoggerProvider
            _set_event_logger_provider(EventLoggerProvider(logger_provider), False)
        except ImportError:
            _logger.debug("OpenTelemetry Events API not available")

    except ImportError as ex:
        _logger.warning("Failed to set up logging pipeline: %s", ex)


def _setup_standalone_metrics(configurations: Dict[str, ConfigurationValue]):
    """Create a MeterProvider when Azure Monitor is not handling it."""
    resource: Resource = configurations[RESOURCE_ARG]  # type: ignore
    views: List[View] = configurations[VIEWS_ARG]  # type: ignore
    readers: list[MetricReader] = configurations[METRIC_READERS_ARG]  # type: ignore

    meter_provider = MeterProvider(
        metric_readers=readers,
        resource=resource,
        views=views,
    )
    set_meter_provider(meter_provider)


def _get_sdk_tracer_provider() -> Optional[TracerProvider]:
    """Get the SDK TracerProvider, unwrapping Azure Monitor's proxy if needed."""
    tp = get_tracer_provider()
    real_tp = getattr(tp, "_real_tracer_provider", tp)
    if isinstance(real_tp, TracerProvider):
        return real_tp
    if isinstance(tp, TracerProvider):
        return tp
    return None


class _EntryPointDistFinder:
    @cached_property
    def _mapping(self):
        return {self._key_for(ep): dist for dist in distributions() for ep in dist.entry_points}

    def dist_for(self, entry_point: EntryPoint):
        dist = getattr(entry_point, "dist", None)
        if dist:
            return dist
        return self._mapping.get(self._key_for(entry_point))

    @staticmethod
    def _key_for(entry_point: EntryPoint):
        return f"{entry_point.group}:{entry_point.name}:{entry_point.value}"


def _setup_instrumentations(configurations: Dict[str, ConfigurationValue]):
    """Set up instrumentations (only called when Azure Monitor is not handling them)."""
    entry_point_finder = _EntryPointDistFinder()
    for entry_point in entry_points(group="opentelemetry_instrumentor"):
        lib_name = entry_point.name
        if lib_name not in _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES:
            continue
        if not _is_instrumentation_enabled(configurations, lib_name):
            _logger.debug("Instrumentation skipped for library %s", entry_point.name)
            continue
        try:
            entry_point_dist = entry_point_finder.dist_for(entry_point)  # type: ignore
            conflict = get_dist_dependency_conflicts(entry_point_dist)  # type: ignore
            if conflict:
                _logger.debug("Skipping instrumentation %s: %s", entry_point.name, conflict)
                continue
            instrumentor: Any = entry_point.load()
            instrumentor().instrument(skip_dep_check=True)
        except Exception as ex:
            _logger.warning("Exception occurred when instrumenting: %s.", lib_name, exc_info=ex)

    # Set up Azure SDK tracing
    if _is_instrumentation_enabled(configurations, _AZURE_SDK_INSTRUMENTATION_NAME):
        try:
            from azure.core.settings import settings
            from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
            settings.tracing_implementation = OpenTelemetrySpan
        except ImportError:
            _logger.debug("Azure SDK tracing not available")
        except Exception as ex:
            _logger.warning("Failed to set Azure SDK tracing: %s", ex)

    _setup_additional_azure_sdk_instrumentations(configurations)


def _setup_additional_azure_sdk_instrumentations(configurations: Dict[str, ConfigurationValue]):
    if _AZURE_SDK_INSTRUMENTATION_NAME not in _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES:
        return
    if not _is_instrumentation_enabled(configurations, _AZURE_SDK_INSTRUMENTATION_NAME):
        return

    instrumentors = [
        ("azure.ai.inference.tracing", "AIInferenceInstrumentor"),
        ("azure.ai.agents.telemetry", "AIAgentsInstrumentor"),
        ("azure.ai.projects.telemetry", "AIProjectInstrumentor"),
    ]

    for module_path, class_name in instrumentors:
        try:
            module = __import__(module_path, fromlist=[class_name])
            instrumentor_class = getattr(module, class_name)
            instrumentor_class().instrument()
        except Exception:
            _logger.debug("Failed to instrument %s.%s", module_path, class_name)
