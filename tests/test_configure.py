# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Tests for use_microsoft_opentelemetry() -- Azure Monitor flow.

Validates that the microsoft distro wrapper correctly delegates to
configure_azure_monitor() from monitor.azureMonitor.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry._configure import (
    use_microsoft_opentelemetry,
)

TEST_RESOURCE = Resource({"service.name": "test-service"})
TEST_CONNECTION_STRING = "InstrumentationKey=test-key;IngestionEndpoint=https://test.in.ai.azure.com/"


class TestUseMicrosoftOpenTelemetry(unittest.TestCase):
    """Tests for use_microsoft_opentelemetry() orchestration."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_azure_monitor_enabled_by_default(self, azure_monitor_mock):
        """Azure Monitor is enabled by default (no args needed)."""
        use_microsoft_opentelemetry()
        azure_monitor_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_remapped(self, azure_monitor_mock):
        """azure_monitor_connection_string is remapped and passed through."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
        )

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_azure_monitor_kwargs_remapped(self, azure_monitor_mock):
        """azure_monitor_ prefixed kwargs are remapped to internal names."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            azure_monitor_exporter_credential="test_cred",
            azure_monitor_enable_live_metrics=False,
            azure_monitor_enable_performance_counters=False,
            azure_monitor_exporter_disable_offline_storage=True,
            azure_monitor_exporter_storage_directory="/tmp/test",
            azure_monitor_browser_sdk_loader_config={"enabled": False},
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        self.assertEqual(actual_kwargs["credential"], "test_cred")
        self.assertEqual(actual_kwargs["enable_live_metrics"], False)
        self.assertEqual(actual_kwargs["enable_performance_counters"], False)
        self.assertEqual(actual_kwargs["disable_offline_storage"], True)
        self.assertEqual(actual_kwargs["storage_directory"], "/tmp/test")
        self.assertEqual(actual_kwargs["browser_sdk_loader_config"], {"enabled": False})

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_general_otel_kwargs_forwarded(self, azure_monitor_mock):
        """General OTel kwargs are forwarded without remapping."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            sampling_ratio=0.5,
            logger_name="test",
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        self.assertEqual(actual_kwargs["sampling_ratio"], 0.5)
        self.assertEqual(actual_kwargs["logger_name"], "test")

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_explicit_disable(self, azure_monitor_mock):
        """Explicitly disabling Azure Monitor skips setup."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            enable_azure_monitor=False,
        )
        azure_monitor_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_enable_key_not_forwarded(self, azure_monitor_mock):
        """enable_azure_monitor is consumed, not forwarded."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            enable_azure_monitor=True,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("enable_azure_monitor", actual_kwargs)


class TestSetupAzureMonitor(unittest.TestCase):
    """Tests for _setup_azure_monitor() delegation."""

    def _make_mock_modules(self):
        """Create mock microsoft.azureMonitor module hierarchy."""
        mock_module = MagicMock()
        return {
            "microsoft": MagicMock(),
            "microsoft.azureMonitor": mock_module,
        }, mock_module

    def test_delegates_to_configure_azure_monitor(self):
        """_setup_azure_monitor calls configure_azure_monitor with the given kwargs."""
        mods, mock_module = self._make_mock_modules()
        with patch.dict(sys.modules, mods):
            from microsoft.opentelemetry._configure import _setup_azure_monitor

            _setup_azure_monitor(
                connection_string=TEST_CONNECTION_STRING,
                resource=TEST_RESOURCE,
            )
            mock_module.configure_azure_monitor.assert_called_once_with(
                connection_string=TEST_CONNECTION_STRING,
                resource=TEST_RESOURCE,
            )

    def test_forwards_standard_config_keys(self):
        """Standard config keys (resource, sampling, processors, etc.) are forwarded."""
        mods, mock_module = self._make_mock_modules()
        with patch.dict(sys.modules, mods):
            from microsoft.opentelemetry._configure import _setup_azure_monitor

            _setup_azure_monitor(
                connection_string=TEST_CONNECTION_STRING,
                resource=TEST_RESOURCE,
                disable_tracing=False,
                disable_logging=False,
                disable_metrics=False,
                span_processors=["sp1"],
                log_record_processors=["lrp1"],
                metric_readers=["mr1"],
                views=["v1"],
                enable_live_metrics=True,
                enable_performance_counters=True,
                sampling_ratio=0.5,
                logger_name="test",
            )
            actual_kwargs = mock_module.configure_azure_monitor.call_args[1]

            self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
            self.assertEqual(actual_kwargs["resource"], TEST_RESOURCE)
            self.assertEqual(actual_kwargs["disable_tracing"], False)
            self.assertEqual(actual_kwargs["span_processors"], ["sp1"])
            self.assertEqual(actual_kwargs["sampling_ratio"], 0.5)
            self.assertEqual(actual_kwargs["logger_name"], "test")

    def test_exception_handled_gracefully(self):
        """If configure_azure_monitor raises, it is caught and logged."""
        mods, mock_module = self._make_mock_modules()
        mock_module.configure_azure_monitor.side_effect = Exception("config error")
        with patch.dict(sys.modules, mods):
            from microsoft.opentelemetry._configure import _setup_azure_monitor

            # Should not raise
            _setup_azure_monitor(connection_string=TEST_CONNECTION_STRING)


class TestEnableKwargsPassthrough(unittest.TestCase):
    """Tests that azure_monitor_ kwargs are remapped and passed through."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_enable_live_metrics_passed_through(self, azure_monitor_mock):
        """azure_monitor_enable_live_metrics is remapped and forwarded."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            azure_monitor_enable_live_metrics=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["enable_live_metrics"], False)

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_enable_performance_counters_passed_through(self, azure_monitor_mock):
        """azure_monitor_enable_performance_counters is remapped and forwarded."""
        use_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            azure_monitor_enable_performance_counters=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["enable_performance_counters"], False)


class TestAllConfigOptions(unittest.TestCase):
    """End-to-end test that every documented configuration option works."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_all_options_end_to_end(self, azure_monitor_mock):
        """Every documented kwarg is accepted, remapped if needed, and forwarded."""
        from logging import Formatter

        formatter = Formatter("%(message)s")

        use_microsoft_opentelemetry(
            # Azure Monitor options (remapped)
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            azure_monitor_exporter_credential="test_cred",
            azure_monitor_enable_live_metrics=False,
            azure_monitor_enable_performance_counters=False,
            azure_monitor_exporter_disable_offline_storage=True,
            azure_monitor_exporter_storage_directory="/tmp/test",
            azure_monitor_browser_sdk_loader_config={"enabled": False},
            # General OTel options (passed through unchanged)
            disable_logging=True,
            disable_tracing=True,
            disable_metrics=True,
            resource=TEST_RESOURCE,
            span_processors=["sp1"],
            log_record_processors=["lrp1"],
            metric_readers=["mr1"],
            views=["v1"],
            logger_name="mylogger",
            logging_formatter=formatter,
            instrumentation_options={"flask": {"enabled": False}},
            enable_trace_based_sampling_for_logs=True,
            sampling_ratio=0.25,
        )

        azure_monitor_mock.assert_called_once()
        actual = azure_monitor_mock.call_args[1]

        # Remapped azure_monitor_ kwargs
        self.assertEqual(actual["connection_string"], TEST_CONNECTION_STRING)
        self.assertEqual(actual["credential"], "test_cred")
        self.assertEqual(actual["enable_live_metrics"], False)
        self.assertEqual(actual["enable_performance_counters"], False)
        self.assertEqual(actual["disable_offline_storage"], True)
        self.assertEqual(actual["storage_directory"], "/tmp/test")
        self.assertEqual(actual["browser_sdk_loader_config"], {"enabled": False})

        # General OTel kwargs passed through unchanged
        self.assertEqual(actual["disable_logging"], True)
        self.assertEqual(actual["disable_tracing"], True)
        self.assertEqual(actual["disable_metrics"], True)
        self.assertEqual(actual["resource"], TEST_RESOURCE)
        self.assertEqual(actual["span_processors"], ["sp1"])
        self.assertEqual(actual["log_record_processors"], ["lrp1"])
        self.assertEqual(actual["metric_readers"], ["mr1"])
        self.assertEqual(actual["views"], ["v1"])
        self.assertEqual(actual["logger_name"], "mylogger")
        self.assertEqual(actual["logging_formatter"], formatter)
        self.assertEqual(actual["instrumentation_options"], {"flask": {"enabled": False}})
        self.assertEqual(actual["enable_trace_based_sampling_for_logs"], True)
        self.assertEqual(actual["sampling_ratio"], 0.25)

        # azure_monitor_ prefixed keys should NOT appear in forwarded kwargs
        for key in actual:
            self.assertFalse(
                key.startswith("azure_monitor_"),
                f"Prefixed key '{key}' should have been remapped",
            )
        self.assertNotIn("enable_azure_monitor", actual)


if __name__ == "__main__":
    unittest.main()
