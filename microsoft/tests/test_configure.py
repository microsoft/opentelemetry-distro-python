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
    configure_microsoft_opentelemetry,
)

TEST_RESOURCE = Resource({"service.name": "test-service"})
TEST_CONNECTION_STRING = (
    "InstrumentationKey=test-key;IngestionEndpoint=https://test.in.ai.azure.com/"
)


class TestConfigureMicrosoftOpenTelemetry(unittest.TestCase):
    """Tests for the top-level configure_microsoft_opentelemetry() orchestration."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_azure_monitor_enabled_with_connection_string(self, azure_monitor_mock):
        """Providing a connection string auto-enables Azure Monitor."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
        )

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_azure_monitor_disabled_without_connection_string(self, azure_monitor_mock):
        """Without a connection string, a warning is logged and setup is skipped."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_extra_kwargs_forwarded(self, azure_monitor_mock):
        """Extra kwargs are forwarded through to _setup_azure_monitor."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            sampling_ratio=0.5,
            logger_name="test",
        )
        azure_monitor_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
            sampling_ratio=0.5,
            logger_name="test",
        )

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_explicit_enable_without_connection_string_warns(self, azure_monitor_mock):
        """Explicitly enabling Azure Monitor without a connection string disables it."""
        configure_microsoft_opentelemetry(disable_azure_monitor_exporter=False)
        azure_monitor_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_explicit_disable_with_connection_string(self, azure_monitor_mock):
        """Explicitly disabling Azure Monitor skips setup even with connection string."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            disable_azure_monitor_exporter=True,
        )
        azure_monitor_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_microsoft_only_keys_not_forwarded(self, azure_monitor_mock):
        """Microsoft-only keys are consumed and not forwarded to _setup_azure_monitor."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            disable_azure_monitor_exporter=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("azure_monitor_connection_string", actual_kwargs)
        self.assertNotIn("disable_azure_monitor_exporter", actual_kwargs)


class TestSetupAzureMonitor(unittest.TestCase):
    """Tests for _setup_azure_monitor() -- the delegation to configure_azure_monitor()."""

    @patch("azure.monitor.opentelemetry.configure_azure_monitor", create=True)
    def test_delegates_to_configure_azure_monitor(self, cam_mock):
        """_setup_azure_monitor calls configure_azure_monitor with the given kwargs."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        _setup_azure_monitor(
            connection_string=TEST_CONNECTION_STRING,
            resource=TEST_RESOURCE,
        )
        cam_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
            resource=TEST_RESOURCE,
        )

    @patch("azure.monitor.opentelemetry.configure_azure_monitor", create=True)
    def test_forwards_standard_config_keys(self, cam_mock):
        """Standard config keys (resource, sampling, processors, etc.) are forwarded."""
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
        actual_kwargs = cam_mock.call_args[1]

        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        self.assertEqual(actual_kwargs["resource"], TEST_RESOURCE)
        self.assertEqual(actual_kwargs["disable_tracing"], False)
        self.assertEqual(actual_kwargs["span_processors"], ["sp1"])
        self.assertEqual(actual_kwargs["sampling_ratio"], 0.5)
        self.assertEqual(actual_kwargs["logger_name"], "test")

    @patch(
        "azure.monitor.opentelemetry.configure_azure_monitor",
        create=True,
        side_effect=Exception("config error"),
    )
    def test_exception_handled_gracefully(self, cam_mock):
        """If configure_azure_monitor raises, it is caught and logged."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        # Should not raise
        _setup_azure_monitor(connection_string=TEST_CONNECTION_STRING)


class TestDisableToEnableRemapping(unittest.TestCase):
    """Tests that disable_* kwargs are remapped to enable_* for configure_azure_monitor."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_live_metrics_remapped(self, azure_monitor_mock):
        """disable_live_metrics=True becomes enable_live_metrics=False."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            disable_live_metrics=True,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("disable_live_metrics", actual_kwargs)
        self.assertEqual(actual_kwargs["enable_live_metrics"], False)

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_performance_counters_remapped(self, azure_monitor_mock):
        """disable_performance_counters=True becomes enable_performance_counters=False."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            disable_performance_counters=True,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("disable_performance_counters", actual_kwargs)
        self.assertEqual(actual_kwargs["enable_performance_counters"], False)

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_false_remapped_to_enable_true(self, azure_monitor_mock):
        """disable_live_metrics=False becomes enable_live_metrics=True."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            disable_live_metrics=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["enable_live_metrics"], True)


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

    @patch.dict(
        "os.environ", {"APPLICATIONINSIGHTS_CONNECTION_STRING": TEST_CONNECTION_STRING}
    )
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_env_var_connection_string_enables_azure_monitor(self, azure_monitor_mock):
        """APPLICATIONINSIGHTS_CONNECTION_STRING env var auto-enables Azure Monitor."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_remapped(self, azure_monitor_mock):
        """azure_monitor_connection_string is remapped to connection_string."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        self.assertNotIn("azure_monitor_connection_string", actual_kwargs)


if __name__ == "__main__":
    unittest.main()
