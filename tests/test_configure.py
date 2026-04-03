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

import sys
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry._configure import (
    configure_microsoft_opentelemetry,
)

TEST_RESOURCE = Resource({"service.name": "test-service"})
TEST_CONNECTION_STRING = (
    "InstrumentationKey=test-key;IngestionEndpoint=https://test.in.ai.azure.com/"
)


class TestConfigureMicrosoftOpenTelemetry(unittest.TestCase):
    """Tests for configure_microsoft_opentelemetry() orchestration."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_azure_monitor_enabled_by_default(self, azure_monitor_mock):
        """Azure Monitor is enabled by default (no args needed)."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_forwarded(self, azure_monitor_mock):
        """connection_string is passed through."""
        configure_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once_with(
            connection_string=TEST_CONNECTION_STRING,
        )

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_extra_kwargs_forwarded(self, azure_monitor_mock):
        """Extra kwargs are forwarded to _setup_azure_monitor."""
        configure_microsoft_opentelemetry(
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
        configure_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_azure_monitor_exporter=True,
        )
        azure_monitor_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_key_not_forwarded(self, azure_monitor_mock):
        """disable_azure_monitor_exporter is consumed, not forwarded."""
        configure_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_azure_monitor_exporter=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("disable_azure_monitor_exporter", actual_kwargs)


class TestSetupAzureMonitor(unittest.TestCase):
    """Tests for _setup_azure_monitor() delegation."""

    def _make_mock_modules(self):
        """Create mock azure.monitor.opentelemetry module hierarchy."""
        mock_module = MagicMock()
        return {
            "azure": MagicMock(),
            "azure.monitor": MagicMock(),
            "azure.monitor.opentelemetry": mock_module,
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


class TestDisableToEnableRemapping(unittest.TestCase):
    """Tests that disable_* kwargs are remapped to enable_*."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_live_metrics_remapped(self, azure_monitor_mock):
        """disable_live_metrics=True becomes enable_live_metrics=False."""
        configure_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_live_metrics=True,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("disable_live_metrics", actual_kwargs)
        self.assertEqual(actual_kwargs["enable_live_metrics"], False)

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_performance_counters_remapped(self, azure_monitor_mock):
        """disable_performance_counters=True remaps correctly."""
        configure_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_performance_counters=True,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertNotIn("disable_performance_counters", actual_kwargs)
        self.assertEqual(actual_kwargs["enable_performance_counters"], False)

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disable_false_remapped_to_enable_true(self, azure_monitor_mock):
        """disable_live_metrics=False becomes enable_live_metrics=True."""
        configure_microsoft_opentelemetry(
            connection_string=TEST_CONNECTION_STRING,
            disable_live_metrics=False,
        )
        actual_kwargs = azure_monitor_mock.call_args[1]
        self.assertEqual(actual_kwargs["enable_live_metrics"], True)


if __name__ == "__main__":
    unittest.main()
