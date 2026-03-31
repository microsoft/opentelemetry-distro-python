# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Tests for configure_microsoft_opentelemetry() — Azure Monitor flow.

Validates that the microsoft distro wrapper correctly delegates to
configure_azure_monitor() from azure-monitor-opentelemetry, remaps
parameters, and orchestrates the multi-step setup pipeline.
"""

import unittest
from unittest.mock import MagicMock, Mock, call, patch

from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry._configure import (
    _MICROSOFT_OTEL_ONLY_KEYS,
    configure_microsoft_opentelemetry,
)

TEST_RESOURCE = Resource({"service.name": "test-service"})
TEST_CONNECTION_STRING = "InstrumentationKey=test-key;IngestionEndpoint=https://test.in.ai.azure.com/"


class TestConfigureMicrosoftOpenTelemetry(unittest.TestCase):
    """Tests for the top-level configure_microsoft_opentelemetry() orchestration."""

    # -----------------------------------------------------------------
    # Azure Monitor enabled — delegation to configure_azure_monitor()
    # -----------------------------------------------------------------

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_azure_monitor_enabled_delegates(
        self,
        config_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When Azure Monitor is enabled, _setup_azure_monitor is called
        and _setup_standalone_providers is NOT called."""
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": False,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once()
        standalone_mock.assert_not_called()
        # Instrumentations are NOT set up by the microsoft distro when AzMon handles them
        instrumentations_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_azure_monitor_disabled_uses_standalone(
        self,
        config_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When Azure Monitor is disabled, standalone providers are created
        and instrumentations are set up by the microsoft distro."""
        config_mock.return_value = {
            "enable_azure_monitor_export": False,
            "enable_otlp_export": False,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_not_called()
        standalone_mock.assert_called_once()
        instrumentations_mock.assert_called_once()

    # -----------------------------------------------------------------
    # OTLP exporter wiring
    # -----------------------------------------------------------------

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._prepare_otlp_metric_reader")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_otlp_enabled_adds_exporters(
        self,
        config_mock,
        otlp_metric_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When OTLP is enabled, OTLP exporters are added and metric reader is prepared."""
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": True,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            enable_otlp_export=True,
        )
        otlp_metric_mock.assert_called_once()
        otlp_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._prepare_otlp_metric_reader")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_otlp_disabled_no_exporters(
        self,
        config_mock,
        otlp_metric_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When OTLP is disabled, no OTLP exporters or metric readers are added."""
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": False,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        otlp_metric_mock.assert_not_called()
        otlp_mock.assert_not_called()

    # -----------------------------------------------------------------
    # A365 exporter wiring
    # -----------------------------------------------------------------

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_a365_enabled_adds_exporter(
        self,
        config_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When A365 is enabled, _add_a365_exporter is called."""
        config_mock.return_value = {
            "enable_azure_monitor_export": False,
            "enable_otlp_export": False,
            "enable_a365_export": True,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(enable_a365_export=True)
        a365_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_a365_disabled_no_exporter(
        self,
        config_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When A365 is disabled, _add_a365_exporter is NOT called."""
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": False,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        a365_mock.assert_not_called()

    # -----------------------------------------------------------------
    # Full pipeline: Azure Monitor + OTLP + A365 together
    # -----------------------------------------------------------------

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._prepare_otlp_metric_reader")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_all_exporters_enabled(
        self,
        config_mock,
        otlp_metric_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """When all exporters are enabled, Azure Monitor sets up providers,
        then OTLP and A365 are added on top."""
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": True,
            "enable_a365_export": True,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            enable_otlp_export=True,
            enable_a365_export=True,
        )
        azure_monitor_mock.assert_called_once()
        standalone_mock.assert_not_called()
        otlp_metric_mock.assert_called_once()
        otlp_mock.assert_called_once()
        a365_mock.assert_called_once()
        # AzMon handles instrumentations, so microsoft distro skips them
        instrumentations_mock.assert_not_called()


class TestSetupAzureMonitor(unittest.TestCase):
    """Tests for _setup_azure_monitor() — the delegation to configure_azure_monitor()."""

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
            # Microsoft-only keys that should NOT be forwarded
            "enable_otlp_export": True,
            "otlp_endpoint": "http://localhost:4318",
            "enable_a365_export": False,
            "enable_genai_openai_instrumentation": True,
        }
        _setup_azure_monitor(configurations)
        cam_mock.assert_called_once()

        # Verify the call kwargs
        actual_kwargs = cam_mock.call_args[1]

        # connection_string should be remapped from azure_monitor_connection_string
        self.assertEqual(actual_kwargs["connection_string"], TEST_CONNECTION_STRING)
        # azure_monitor_connection_string should NOT be in the forwarded kwargs
        self.assertNotIn("azure_monitor_connection_string", actual_kwargs)

    @patch("azure.monitor.opentelemetry.configure_azure_monitor")
    def test_filters_microsoft_only_keys(self, cam_mock):
        """Microsoft-only keys (OTLP, A365, GenAI) are NOT forwarded to configure_azure_monitor."""
        from microsoft.opentelemetry._configure import _setup_azure_monitor

        configurations = {
            "azure_monitor_connection_string": TEST_CONNECTION_STRING,
            "resource": TEST_RESOURCE,
            "enable_otlp_export": True,
            "otlp_endpoint": "http://localhost:4318",
            "otlp_protocol": "http/protobuf",
            "otlp_headers": "key=value",
            "enable_azure_monitor_export": True,
            "enable_a365_export": True,
            "a365_token_resolver": lambda a, t: None,
            "a365_cluster_category": "prod",
            "a365_exporter_options": None,
            "enable_a365_openai_instrumentation": True,
            "enable_a365_langchain_instrumentation": False,
            "enable_a365_semantickernel_instrumentation": False,
            "enable_a365_agentframework_instrumentation": True,
            "enable_genai_openai_instrumentation": True,
            "enable_genai_openai_agents_instrumentation": False,
            "enable_genai_langchain_instrumentation": False,
        }
        _setup_azure_monitor(configurations)
        actual_kwargs = cam_mock.call_args[1]

        for key in _MICROSOFT_OTEL_ONLY_KEYS:
            self.assertNotIn(key, actual_kwargs, f"Microsoft-only key '{key}' leaked to configure_azure_monitor")

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

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_enables_azure_monitor(
        self,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """Providing azure_monitor_connection_string auto-enables Azure Monitor."""
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        azure_monitor_mock.assert_called_once()
        standalone_mock.assert_not_called()

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_no_connection_string_uses_standalone(
        self,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """Without a connection string, Azure Monitor is disabled and standalone providers are used."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_not_called()
        standalone_mock.assert_called_once()

    @patch.dict("os.environ", {"APPLICATIONINSIGHTS_CONNECTION_STRING": TEST_CONNECTION_STRING})
    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_env_var_connection_string_enables_azure_monitor(
        self,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """APPLICATIONINSIGHTS_CONNECTION_STRING env var auto-enables Azure Monitor."""
        configure_microsoft_opentelemetry()
        azure_monitor_mock.assert_called_once()
        standalone_mock.assert_not_called()


class TestPipelineOrdering(unittest.TestCase):
    """Tests that the setup steps execute in the correct order."""

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._prepare_otlp_metric_reader")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_azure_monitor_before_otlp_before_a365(
        self,
        config_mock,
        otlp_metric_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """Azure Monitor is set up first, then OTLP, then A365."""
        call_order = []
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": True,
            "enable_a365_export": True,
            "disable_metrics": False,
        }
        azure_monitor_mock.side_effect = lambda *a, **k: call_order.append("azure_monitor")
        otlp_mock.side_effect = lambda *a, **k: call_order.append("otlp")
        a365_mock.side_effect = lambda *a, **k: call_order.append("a365")

        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
            enable_otlp_export=True,
            enable_a365_export=True,
        )

        self.assertIn("azure_monitor", call_order)
        self.assertIn("otlp", call_order)
        self.assertIn("a365", call_order)
        self.assertLess(
            call_order.index("azure_monitor"),
            call_order.index("otlp"),
            "Azure Monitor must be set up before OTLP",
        )
        self.assertLess(
            call_order.index("otlp"),
            call_order.index("a365"),
            "OTLP must be set up before A365",
        )


class TestGenAIAndA365Instrumentations(unittest.TestCase):
    """Tests that GenAI and A365 instrumentations are always invoked."""

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_genai_and_a365_instrumentations_always_called(
        self,
        config_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """GenAI and A365 instrumentation setup is always called regardless of exporter config."""
        config_mock.return_value = {
            "enable_azure_monitor_export": True,
            "enable_otlp_export": False,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry(
            azure_monitor_connection_string=TEST_CONNECTION_STRING,
        )
        a365_instr_mock.assert_called_once()
        genai_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_genai_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_a365_instrumentations")
    @patch("microsoft.opentelemetry._configure._setup_instrumentations")
    @patch("microsoft.opentelemetry._configure._add_a365_exporter")
    @patch("microsoft.opentelemetry._configure._add_otlp_exporters")
    @patch("microsoft.opentelemetry._configure._setup_standalone_providers")
    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    @patch("microsoft.opentelemetry._configure._get_configurations")
    def test_genai_and_a365_instrumentations_called_standalone_mode(
        self,
        config_mock,
        azure_monitor_mock,
        standalone_mock,
        otlp_mock,
        a365_mock,
        instrumentations_mock,
        a365_instr_mock,
        genai_mock,
    ):
        """GenAI and A365 instrumentations are called even without any exporter."""
        config_mock.return_value = {
            "enable_azure_monitor_export": False,
            "enable_otlp_export": False,
            "enable_a365_export": False,
            "disable_metrics": False,
        }
        configure_microsoft_opentelemetry()
        a365_instr_mock.assert_called_once()
        genai_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
