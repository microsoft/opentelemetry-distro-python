# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Integration tests for the microsoft.opentelemetry distro package.

Validates public API surface, standalone provider setup,
environment variable handling, and error paths.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry._configure import (
    _setup_standalone_providers,
    _setup_standalone_tracing,
    _setup_standalone_logging,
    _setup_standalone_metrics,
    _get_sdk_tracer_provider,
    _setup_azure_monitor,
    configure_microsoft_opentelemetry,
)
from microsoft.opentelemetry._constants import (
    DISABLE_TRACING_ARG,
    DISABLE_LOGGING_ARG,
    DISABLE_METRICS_ARG,
    RESOURCE_ARG,
    SAMPLING_RATIO_ARG,
    SPAN_PROCESSORS_ARG,
    LOG_RECORD_PROCESSORS_ARG,
    METRIC_READERS_ARG,
    VIEWS_ARG,
    LOGGER_NAME_ARG,
    LOGGING_FORMATTER_ARG,
    ENABLE_AZURE_MONITOR_EXPORTER_ARG,
    CONNECTION_STRING_ARG,
    SAMPLING_ARG,
    SAMPLER_TYPE,
)

TEST_RESOURCE = Resource({"service.name": "integration-test"})
TEST_CONNECTION_STRING = (
    "InstrumentationKey=test-key;"
    "IngestionEndpoint=https://test.in.ai.azure.com/"
)


def _base_configurations(**overrides):
    """Return a minimal valid configuration dict for standalone mode."""
    config = {
        DISABLE_TRACING_ARG: False,
        DISABLE_LOGGING_ARG: False,
        DISABLE_METRICS_ARG: False,
        RESOURCE_ARG: TEST_RESOURCE,
        SPAN_PROCESSORS_ARG: [],
        LOG_RECORD_PROCESSORS_ARG: [],
        METRIC_READERS_ARG: [],
        VIEWS_ARG: [],
        LOGGER_NAME_ARG: "",
    }
    config.update(overrides)
    return config


# ── Public API Surface ──────────────────────────────────────────────────


class TestPublicAPISurface(unittest.TestCase):
    """Validate that the package exposes the intended public API."""

    def test_configure_importable_from_package_root(self):
        from microsoft.opentelemetry import configure_microsoft_opentelemetry as fn
        self.assertTrue(callable(fn))

    def test_version_accessible(self):
        from microsoft.opentelemetry import __version__
        self.assertIsInstance(__version__, str)
        self.assertTrue(len(__version__) > 0)

    def test_all_exports_only_configure(self):
        from microsoft.opentelemetry import __all__
        self.assertEqual(__all__, ["configure_microsoft_opentelemetry"])

    def test_constants_reexported(self):
        """Microsoft-specific constants should be importable."""
        from microsoft.opentelemetry._constants import (
            CONNECTION_STRING_ARG,
        )
        self.assertIsInstance(CONNECTION_STRING_ARG, str)

    def test_types_reexported(self):
        from microsoft.opentelemetry._types import ConfigurationValue
        self.assertIsNotNone(ConfigurationValue)

    def test_utils_instrumentation_reexported(self):
        from microsoft.opentelemetry._utils.instrumentation import (
            get_dist_dependency_conflicts,
        )
        self.assertTrue(callable(get_dist_dependency_conflicts))


# ── Standalone Provider Setup ────────────────────────────────────────────


class TestStandaloneTracingSetup(unittest.TestCase):
    """Tests for _setup_standalone_tracing."""

    @patch("microsoft.opentelemetry._configure.set_tracer_provider")
    def test_creates_tracer_provider_with_resource(self, set_tp_mock):
        config = _base_configurations()
        _setup_standalone_tracing(config)
        set_tp_mock.assert_called_once()
        tp = set_tp_mock.call_args[0][0]
        self.assertEqual(tp.resource, TEST_RESOURCE)

    @patch("microsoft.opentelemetry._configure.set_tracer_provider")
    def test_creates_tracer_provider_with_sampling_ratio(self, set_tp_mock):
        config = _base_configurations(**{SAMPLING_RATIO_ARG: 0.5})
        _setup_standalone_tracing(config)
        set_tp_mock.assert_called_once()
        tp = set_tp_mock.call_args[0][0]
        self.assertIsNotNone(tp.sampler)

    @patch("microsoft.opentelemetry._configure.set_tracer_provider")
    def test_adds_custom_span_processors(self, set_tp_mock):
        mock_processor = MagicMock()
        config = _base_configurations(**{SPAN_PROCESSORS_ARG: [mock_processor]})
        _setup_standalone_tracing(config)
        tp = set_tp_mock.call_args[0][0]
        # The processor should have been added
        self.assertIn(mock_processor, tp._active_span_processor._span_processors)


class TestStandaloneLoggingSetup(unittest.TestCase):
    """Tests for _setup_standalone_logging."""

    @patch("opentelemetry._logs.set_logger_provider")
    def test_creates_logger_provider(self, set_lp_mock):
        from opentelemetry.sdk._logs import LoggerProvider
        config = _base_configurations()
        _setup_standalone_logging(config)
        set_lp_mock.assert_called_once()
        lp = set_lp_mock.call_args[0][0]
        self.assertIsInstance(lp, LoggerProvider)

    @patch("opentelemetry._logs.set_logger_provider")
    def test_adds_custom_log_processors(self, set_lp_mock):
        mock_processor = MagicMock()
        config = _base_configurations(**{LOG_RECORD_PROCESSORS_ARG: [mock_processor]})
        _setup_standalone_logging(config)
        set_lp_mock.assert_called_once()


class TestStandaloneMetricsSetup(unittest.TestCase):
    """Tests for _setup_standalone_metrics."""

    @patch("microsoft.opentelemetry._configure.set_meter_provider")
    def test_creates_meter_provider_with_resource(self, set_mp_mock):
        config = _base_configurations()
        _setup_standalone_metrics(config)
        set_mp_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure.set_meter_provider")
    def test_creates_meter_provider_with_custom_readers(self, set_mp_mock):
        mock_reader = MagicMock()
        config = _base_configurations(**{METRIC_READERS_ARG: [mock_reader]})
        _setup_standalone_metrics(config)
        set_mp_mock.assert_called_once()


class TestStandaloneProvidersOrchestration(unittest.TestCase):
    """Tests for _setup_standalone_providers signal enable/disable flags."""

    @patch("microsoft.opentelemetry._configure._setup_standalone_metrics")
    @patch("microsoft.opentelemetry._configure._setup_standalone_logging")
    @patch("microsoft.opentelemetry._configure._setup_standalone_tracing")
    def test_all_signals_enabled(self, tracing, logging, metrics):
        config = _base_configurations()
        _setup_standalone_providers(config)
        tracing.assert_called_once()
        logging.assert_called_once()
        metrics.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_standalone_metrics")
    @patch("microsoft.opentelemetry._configure._setup_standalone_logging")
    @patch("microsoft.opentelemetry._configure._setup_standalone_tracing")
    def test_tracing_disabled(self, tracing, logging, metrics):
        config = _base_configurations(**{DISABLE_TRACING_ARG: True})
        _setup_standalone_providers(config)
        tracing.assert_not_called()
        logging.assert_called_once()
        metrics.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_standalone_metrics")
    @patch("microsoft.opentelemetry._configure._setup_standalone_logging")
    @patch("microsoft.opentelemetry._configure._setup_standalone_tracing")
    def test_logging_disabled(self, tracing, logging, metrics):
        config = _base_configurations(**{DISABLE_LOGGING_ARG: True})
        _setup_standalone_providers(config)
        tracing.assert_called_once()
        logging.assert_not_called()
        metrics.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_standalone_metrics")
    @patch("microsoft.opentelemetry._configure._setup_standalone_logging")
    @patch("microsoft.opentelemetry._configure._setup_standalone_tracing")
    def test_metrics_disabled(self, tracing, logging, metrics):
        config = _base_configurations(**{DISABLE_METRICS_ARG: True})
        _setup_standalone_providers(config)
        tracing.assert_called_once()
        logging.assert_called_once()
        metrics.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_standalone_metrics")
    @patch("microsoft.opentelemetry._configure._setup_standalone_logging")
    @patch("microsoft.opentelemetry._configure._setup_standalone_tracing")
    def test_all_signals_disabled(self, tracing, logging, metrics):
        config = _base_configurations(**{
            DISABLE_TRACING_ARG: True,
            DISABLE_LOGGING_ARG: True,
            DISABLE_METRICS_ARG: True,
        })
        _setup_standalone_providers(config)
        tracing.assert_not_called()
        logging.assert_not_called()
        metrics.assert_not_called()


# ── Azure Monitor Error Handling ─────────────────────────────────────────


class TestAzureMonitorImportError(unittest.TestCase):
    """Tests for _setup_azure_monitor import error handling."""

    def test_warns_when_azure_monitor_not_installed(self):
        with patch.dict("sys.modules", {"azure.monitor.opentelemetry": None}):
            with self.assertLogs("microsoft.opentelemetry._configure", level="WARNING") as cm:
                _setup_azure_monitor({CONNECTION_STRING_ARG: TEST_CONNECTION_STRING})
            self.assertTrue(
                any("not installed" in msg for msg in cm.output),
            )


# ── _get_sdk_tracer_provider ────────────────────────────────────────────


class TestGetSdkTracerProvider(unittest.TestCase):
    """Tests for _get_sdk_tracer_provider helper."""

    @patch("microsoft.opentelemetry._configure.get_tracer_provider")
    def test_returns_sdk_tracer_provider(self, mock_get):
        from opentelemetry.sdk.trace import TracerProvider
        tp = TracerProvider(resource=TEST_RESOURCE)
        mock_get.return_value = tp
        result = _get_sdk_tracer_provider()
        self.assertIs(result, tp)

    @patch("microsoft.opentelemetry._configure.get_tracer_provider")
    def test_unwraps_azure_monitor_proxy(self, mock_get):
        from opentelemetry.sdk.trace import TracerProvider
        real_tp = TracerProvider(resource=TEST_RESOURCE)
        proxy = MagicMock()
        proxy._real_tracer_provider = real_tp
        mock_get.return_value = proxy
        result = _get_sdk_tracer_provider()
        self.assertIs(result, real_tp)

    @patch("microsoft.opentelemetry._configure.get_tracer_provider")
    def test_returns_none_for_noop(self, mock_get):
        mock_get.return_value = MagicMock(spec=[])  # no _real_tracer_provider
        result = _get_sdk_tracer_provider()
        self.assertIsNone(result)


# ── Environment Variable Handling ────────────────────────────────────────


class TestEnvironmentVariableConfiguration(unittest.TestCase):
    """Tests for env var driven configuration."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_env_var_enables_azure_monitor(
        self, az_mock
    ):
        env = {"APPLICATIONINSIGHTS_CONNECTION_STRING": TEST_CONNECTION_STRING}
        with patch.dict(os.environ, env, clear=False):
            configure_microsoft_opentelemetry()
        az_mock.assert_called_once()
        config = az_mock.call_args[0][0]
        self.assertTrue(config.get(ENABLE_AZURE_MONITOR_EXPORTER_ARG))

    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    def test_no_connection_string_uses_standalone(
        self, standalone_mock
    ):
        env_remove = [
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
        ]
        with patch.dict(os.environ, {}, clear=False):
            for key in env_remove:
                os.environ.pop(key, None)
            configure_microsoft_opentelemetry()
        standalone_mock.assert_called_once()


# ── End-to-End Standalone Mode ───────────────────────────────────────────


class TestEndToEndStandaloneMode(unittest.TestCase):
    """End-to-end test: configure with no Azure Monitor, verify providers are set."""

    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    def test_standalone_mode_sets_providers(self, instr_mock):
        """When no connection string, standalone providers should be created."""
        env_remove = [
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
        ]
        with patch.dict(os.environ, {}, clear=False):
            for key in env_remove:
                os.environ.pop(key, None)
            configure_microsoft_opentelemetry(
                resource=TEST_RESOURCE,
                disable_tracing=False,
                disable_logging=False,
                disable_metrics=False,
            )

        # Instrumentations should be called in standalone mode
        instr_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
