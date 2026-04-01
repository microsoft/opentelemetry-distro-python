# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Tests for configure_microsoft_opentelemetry() -- Azure Monitor flow.

Validates that the microsoft distro wrapper correctly delegates to
configure_azure_monitor() from azure-monitor-opentelemetry and remaps
parameters.
"""

import unittest
from unittest.mock import patch

from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry._configure import (
    _MICROSOFT_OTEL_ONLY_KEYS,
    configure_microsoft_opentelemetry,
)

TEST_RESOURCE = Resource({"service.name": "test-service"})
TEST_CONNECTION_STRING = "InstrumentationKey=test-key;IngestionEndpoint=https://test.in.ai.azure.com/"


class TestConfigureMicrosoftOpenTelemetry(unittest.TestCase):
    """Tests for the top-level configure_microsoft_opentelemetry() orchestration."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_azure_monitor_enabled_delegates(self, config_mock, azure_monitor_mock):
        """When Azure Monitor is enabled, _setup_azure_monitor is called."""
        config_mock.return_value = {"enable_azure_monitor_export": True}
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_azure_monitor_disabled_warns(self, config_mock, azure_monitor_mock):
        """When Azure Monitor is disabled, a warning is logged."""
        config_mock.return_value = {"enable_azure_monitor_export": False}
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_not_called()


class TestSetupAzureMonitor(unittest.TestCase):
    """Tests for _setup_azure_monitor() -- the delegation to configure_azure_monitor()."""

    @patch("azure.monitor.opentelemetry.configure_azure_monitor")
    def test_delegates_to_configure_azure_monitor(self, cam_mock):
        """_setup_azure_monitor calls configure_azure_monitor with remapped kwargs."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        configurations = {
            "azure_monitor_connection_string": TEST_CONNECTION_STRING,
            "disable_tracing": False,
            "disable_logging": False,
            "disable_metrics": False,
            "resource": TEST_RESOURCE,
            "span_processors": [],
            "log_record_processors": [],
            "metric_readers": [],
            "views": [],
            "enable_live_metrics": True,
            "enable_performance_counters": True,
            "enable_azure_monitor_export": True,
        }
        _setup_azure_monitor(configurations)
        cam_mock.assert_called_once()

        actual_kwargs = cam_mock.call_args[1]
        # connection_string should be remapped from azure_monitor_connection_string
        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        # azure_monitor_connection_string should NOT be in the forwarded kwargs
        self.assertNotIn("azure_monitor_connection_string", actual_kwargs)

    @patch("azure.monitor.opentelemetry.configure_azure_monitor")
    def test_filters_microsoft_only_keys(self, cam_mock):
        """Microsoft-only keys are NOT forwarded to configure_azure_monitor."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        configurations = {
            "azure_monitor_connection_string": TEST_CONNECTION_STRING,
            "resource": TEST_RESOURCE,
            "enable_azure_monitor_export": True,
        }
        _setup_azure_monitor(configurations)
        actual_kwargs = cam_mock.call_args[1]

        for key in _MICROSOFT_OTEL_ONLY_KEYS:
            self.assertNotIn(key, actual_kwargs,
                             f"Microsoft-only key '{key}' leaked to configure_azure_monitor")

    @patch("azure.monitor.opentelemetry.configure_azure_monitor")
    def test_forwards_standard_config_keys(self, cam_mock):
        """Standard config keys (resource, sampling, processors, etc.) are forwarded."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        configurations = {
            "azure_monitor_connection_string": TEST_CONNECTION_STRING,
            "resource": TEST_RESOURCE,
            "disable_tracing": False,
            "disable_logging": False,
            "disable_metrics": False,
            "span_processors": ["sp1"],
            "log_record_processors": ["lrp1"],
            "metric_readers": ["mr1"],
            "views": ["v1"],
            "enable_live_metrics": True,
            "enable_performance_counters": True,
            "sampling_ratio": 0.5,
            "logger_name": "test",
        }
        _setup_azure_monitor(configurations)
        actual_kwargs = cam_mock.call_args[1]

        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        self.assertEqual(actual_kwargs["resource"], TEST_RESOURCE)
        self.assertEqual(actual_kwargs["disable_tracing"], False)
        self.assertEqual(actual_kwargs["span_processors"], ["sp1"])
        self.assertEqual(actual_kwargs["sampling_ratio"], 0.5)
        self.assertEqual(actual_kwargs["logger_name"], "test")

    @patch(
        "azure.monitor.opentelemetry.configure_azure_monitor",
        side_effect=Exception("config error"),
    )
    def test_exception_handled_gracefully(self, cam_mock):
        """If configure_azure_monitor raises, it is caught and logged."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor
        # Should not raise
        _setup_azure_monitor({"azure_monitor_connection_string": TEST_CONNECTION_STRING})


class TestConnectionStringRemapping(unittest.TestCase):
    """Tests that azure_monitor_connection_string is correctly handled."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_enables_azure_monitor(self, azure_monitor_mock):
        """Providing azure_monitor_connection_string auto-enables Azure Monitor."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_no_connection_string_does_not_call_azure_monitor(self, azure_monitor_mock):
        """Without a connection string, Azure Monitor setup is not called."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_not_called()

    @patch.dict("os.environ", {"APPLICATIONINSIGHTS_CONNECTION_STRING": TEST_CONNECTION_STRING})
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_env_var_connection_string_enables_azure_monitor(self, azure_monitor_mock):
        """APPLICATIONINSIGHTS_CONNECTION_STRING env var auto-enables Azure Monitor."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
