# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Tests for use_microsoft_opentelemetry() -- Azure Monitor flow.

Validates that the microsoft distro wrapper correctly delegates to
configure_azure_monitor() from azure-monitor-opentelemetry.
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
    def test_connection_string_forwarded(self, azure_monitor_mock):
        """connection_string is passed through."""
        use_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
        )

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_extra_kwargs_forwarded(self, azure_monitor_mock):
        """Extra kwargs are forwarded to _setup_azure_monitor."""
        use_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            sampling_ratio=0.5,
            logger_name="test",
        )
        azure_monitor_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
            sampling_ratio=0.5,
            logger_name="test",
        )

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_explicit_disable(self, azure_monitor_mock):
        """Explicitly disabling Azure Monitor skips setup."""
        use_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_azure_monitor_exporter=True,
        )
        azure_monitor_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_key_not_forwarded(self, azure_monitor_mock):
        """disable_azure_monitor_exporter is consumed, not forwarded."""
        use_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_azure_monitor_exporter=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("disable_azure_monitor_exporter", actual_kwargs)


class TestSetupAzureMonitor(unittest.TestCase):
    """Tests for _setup_azure_monitor() delegation."""

    @patch("microsoft.opentelemetry._configure.configure_azure_monitor")
    def test_delegates_to_configure_azure_monitor(self, mock_configure):
        """_setup_azure_monitor calls configure_azure_monitor with the given kwargs."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        _setup_azure_monitor(
            connection_string=TEST_CONNECTION_STRING,
            resource=TEST_RESOURCE,
        )
        mock_configure.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
            resource=TEST_RESOURCE,
        )

    @patch("microsoft.opentelemetry._configure.configure_azure_monitor")
    def test_forwards_standard_config_keys(self, mock_configure):
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
        actual_kwargs = mock_configure.call_args[1]

        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        self.assertEqual(actual_kwargs["resource"], TEST_RESOURCE)
        self.assertEqual(actual_kwargs["disable_tracing"], False)
        self.assertEqual(actual_kwargs["span_processors"], ["sp1"])
        self.assertEqual(actual_kwargs["sampling_ratio"], 0.5)
        self.assertEqual(actual_kwargs["logger_name"], "test")

    @patch("microsoft.opentelemetry._configure.configure_azure_monitor")
    def test_exception_handled_gracefully(self, mock_configure):
        """If configure_azure_monitor raises, it is caught and logged."""
        mock_configure.side_effect = Exception("config error")
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        # Should not raise
        _setup_azure_monitor(connection_string=TEST_CONNECTION_STRING)


class TestEnableKwargsPassthrough(unittest.TestCase):
    """Tests that enable_* kwargs are passed through directly."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_enable_live_metrics_passed_through(self, azure_monitor_mock):
        """enable_live_metrics is forwarded directly."""
        use_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            enable_live_metrics=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["enable_live_metrics"], False)

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_enable_performance_counters_passed_through(self, azure_monitor_mock):
        """enable_performance_counters is forwarded directly."""
        use_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            enable_performance_counters=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["enable_performance_counters"], False)


if __name__ == "__main__":
    unittest.main()
