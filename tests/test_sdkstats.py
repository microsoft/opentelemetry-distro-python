# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Tests for the _sdkstats package — state, metrics, and manager."""

import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from microsoft.opentelemetry._sdkstats._state import (
    SdkStatsFeature,
    SdkStatsInstrumentation,
    _INSTRUMENTATION_NAME_MAP,
    _SDKSTATS_DISABLED_ENV,
    _APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL,
    _SDKSTATS_STATE,
    _STATE_LOCK,
    get_sdkstats_feature_flags,
    get_sdkstats_instrumentation_flags,
    get_sdkstats_shutdown,
    is_sdkstats_enabled,
    set_sdkstats_feature,
    set_sdkstats_feature_bits,
    set_sdkstats_instrumentation,
    set_sdkstats_instrumentation_bits,
    set_sdkstats_instrumentation_by_name,
    set_sdkstats_shutdown,
)
from microsoft.opentelemetry._sdkstats._utils import (
    REQUEST_SUCCESS_NAME,
    drain,
    record_success,
    reset_all,
)
from microsoft.opentelemetry._sdkstats._otlp_wrapper import (
    _NetworkStatsLogExporter,
    _NetworkStatsMetricExporter,
    _NetworkStatsSpanExporter,
)


def _reset_state():
    """Reset module-level state between tests."""
    with _STATE_LOCK:
        _SDKSTATS_STATE["SHUTDOWN"] = False
        _SDKSTATS_STATE["FEATURE_FLAGS"] = SdkStatsFeature.NONE
        _SDKSTATS_STATE["INSTRUMENTATION_FLAGS"] = SdkStatsInstrumentation.NONE
    reset_all()


class TestSdkStatsEnabled(unittest.TestCase):
    """Tests for is_sdkstats_enabled()."""

    def setUp(self):
        _reset_state()
        # Clean env
        os.environ.pop(_SDKSTATS_DISABLED_ENV, None)
        os.environ.pop(_APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL, None)

    def tearDown(self):
        os.environ.pop(_SDKSTATS_DISABLED_ENV, None)
        os.environ.pop(_APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL, None)

    def test_enabled_by_default(self):
        self.assertTrue(is_sdkstats_enabled())

    def test_disabled_by_new_env_var(self):
        os.environ[_SDKSTATS_DISABLED_ENV] = "true"
        self.assertFalse(is_sdkstats_enabled())

    def test_disabled_by_legacy_env_var(self):
        os.environ[_APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL] = "True"
        self.assertFalse(is_sdkstats_enabled())

    def test_disabled_by_1(self):
        os.environ[_SDKSTATS_DISABLED_ENV] = "1"
        self.assertFalse(is_sdkstats_enabled())

    def test_disabled_by_on(self):
        os.environ[_SDKSTATS_DISABLED_ENV] = "on"
        self.assertFalse(is_sdkstats_enabled())

    def test_enabled_with_random_value(self):
        os.environ[_SDKSTATS_DISABLED_ENV] = "banana"
        self.assertTrue(is_sdkstats_enabled())


class TestSdkStatsShutdown(unittest.TestCase):
    """Tests for shutdown state."""

    def setUp(self):
        _reset_state()

    def test_shutdown_default_false(self):
        self.assertFalse(get_sdkstats_shutdown())

    def test_set_shutdown(self):
        set_sdkstats_shutdown(True)
        self.assertTrue(get_sdkstats_shutdown())

    def test_set_shutdown_false(self):
        set_sdkstats_shutdown(True)
        set_sdkstats_shutdown(False)
        self.assertFalse(get_sdkstats_shutdown())


class TestSdkStatsFeatureFlags(unittest.TestCase):
    """Tests for feature flag state."""

    def setUp(self):
        _reset_state()

    def test_default_none(self):
        self.assertEqual(get_sdkstats_feature_flags(), 0)

    def test_set_single_flag(self):
        set_sdkstats_feature(SdkStatsFeature.DISTRO)
        self.assertEqual(get_sdkstats_feature_flags(), SdkStatsFeature.DISTRO)

    def test_set_multiple_flags(self):
        set_sdkstats_feature(SdkStatsFeature.DISTRO)
        set_sdkstats_feature(SdkStatsFeature.OTLP_EXPORT)
        expected = SdkStatsFeature.DISTRO | SdkStatsFeature.OTLP_EXPORT
        self.assertEqual(get_sdkstats_feature_flags(), expected)

    def test_idempotent_set(self):
        set_sdkstats_feature(SdkStatsFeature.A365_EXPORT)
        set_sdkstats_feature(SdkStatsFeature.A365_EXPORT)
        self.assertEqual(get_sdkstats_feature_flags(), SdkStatsFeature.A365_EXPORT)

    def test_all_features_have_unique_bits(self):
        seen = set()
        for member in SdkStatsFeature:
            if member == SdkStatsFeature.NONE:
                continue
            self.assertNotIn(int(member), seen, f"Duplicate bit for {member.name}")
            seen.add(int(member))


class TestSdkStatsInstrumentationFlags(unittest.TestCase):
    """Tests for instrumentation flag state."""

    def setUp(self):
        _reset_state()

    def test_default_none(self):
        self.assertEqual(get_sdkstats_instrumentation_flags(), 0)

    def test_set_by_enum(self):
        set_sdkstats_instrumentation(SdkStatsInstrumentation.DJANGO)
        self.assertEqual(
            get_sdkstats_instrumentation_flags(),
            SdkStatsInstrumentation.DJANGO,
        )

    def test_set_by_name(self):
        set_sdkstats_instrumentation_by_name("fastapi")
        self.assertEqual(
            get_sdkstats_instrumentation_flags(),
            SdkStatsInstrumentation.FASTAPI,
        )

    def test_set_unknown_name_ignored(self):
        set_sdkstats_instrumentation_by_name("nonexistent_lib")
        self.assertEqual(get_sdkstats_instrumentation_flags(), 0)

    def test_multiple_instrumentations(self):
        set_sdkstats_instrumentation_by_name("django")
        set_sdkstats_instrumentation_by_name("openai")
        expected = SdkStatsInstrumentation.DJANGO | SdkStatsInstrumentation.OPENAI_V2
        self.assertEqual(get_sdkstats_instrumentation_flags(), expected)

    def test_name_map_covers_supported_libraries(self):
        """Every name in the map resolves to a non-zero flag."""
        for name, flag in _INSTRUMENTATION_NAME_MAP.items():
            self.assertNotEqual(flag, 0, f"Flag for {name} is zero")


class TestSdkStatsThreadSafety(unittest.TestCase):
    """Ensure concurrent flag updates are safe."""

    def setUp(self):
        _reset_state()

    def test_concurrent_feature_flag_updates(self):
        flags = list(SdkStatsFeature)
        flags = [f for f in flags if f != SdkStatsFeature.NONE]
        errors = []

        def worker(flag):
            try:
                for _ in range(100):
                    set_sdkstats_feature(flag)
            except Exception as e:  # pylint: disable=broad-exception-caught
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f,)) for f in flags]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

        # All flags should be set
        expected = SdkStatsFeature.NONE
        for f in flags:
            expected |= f
        self.assertEqual(get_sdkstats_feature_flags(), expected)


class TestSdkStatsMetrics(unittest.TestCase):
    """Tests for the SdkStatsMetrics observable gauges."""

    def setUp(self):
        _reset_state()

    def test_feature_observation_empty_when_no_flags(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        mp = MeterProvider()
        try:
            metrics = SdkStatsMetrics(mp)
            obs = list(metrics._observe_features(MagicMock()))
            self.assertEqual(obs, [])
        finally:
            mp.shutdown()

    def test_feature_observation_emitted_with_flags(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        set_sdkstats_feature(SdkStatsFeature.DISTRO)
        mp = MeterProvider()
        try:
            metrics = SdkStatsMetrics(mp)
            obs = list(metrics._observe_features(MagicMock()))
            self.assertEqual(len(obs), 1)
            self.assertEqual(obs[0].value, 1)
            attrs = obs[0].attributes
            assert attrs is not None
            self.assertEqual(attrs["feature"], int(SdkStatsFeature.DISTRO))
            self.assertEqual(attrs["type"], 0)  # FEATURE
        finally:
            mp.shutdown()

    def test_instrumentation_observation_emitted(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        set_sdkstats_instrumentation(SdkStatsInstrumentation.FASTAPI)
        mp = MeterProvider()
        try:
            metrics = SdkStatsMetrics(mp)
            obs = list(metrics._observe_instrumentations(MagicMock()))
            self.assertEqual(len(obs), 1)
            attrs = obs[0].attributes
            assert attrs is not None
            self.assertEqual(attrs["feature"], int(SdkStatsInstrumentation.FASTAPI))
            self.assertEqual(attrs["type"], 1)  # INSTRUMENTATION
        finally:
            mp.shutdown()

    def test_enable_azure_monitor_skips_feature_and_instrumentation_gauges(self):
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        meter_mock = MagicMock()
        meter_provider_mock = MagicMock()
        meter_provider_mock.get_meter.return_value = meter_mock

        SdkStatsMetrics(meter_provider_mock, enable_azure_monitor=True)

        callbacks = []
        for call in meter_mock.create_observable_gauge.call_args_list:
            callback_list = call.kwargs.get("callbacks", [])
            callbacks.extend(callback_list)

        callback_names = {cb.__name__ for cb in callbacks}
        self.assertNotIn("_observe_features", callback_names)
        self.assertNotIn("_observe_instrumentations", callback_names)
        self.assertIn("_observe_request_success_count", callback_names)


class TestSdkStatsManager(unittest.TestCase):
    """Tests for the SdkStatsManager singleton."""

    def setUp(self):
        _reset_state()
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        SdkStatsManager._reset()

    def tearDown(self):
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        SdkStatsManager._reset()

    def test_singleton(self):
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        a = SdkStatsManager()
        b = SdkStatsManager()
        self.assertIs(a, b)

    def test_initialize_standalone(self):
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        reader = InMemoryMetricReader()
        manager = SdkStatsManager()
        result = manager.initialize_standalone(reader)
        self.assertTrue(result)
        self.assertTrue(manager.is_initialized)

    def test_initialize_standalone_disabled(self):
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        os.environ[_SDKSTATS_DISABLED_ENV] = "true"
        try:
            reader = InMemoryMetricReader()
            manager = SdkStatsManager()
            result = manager.initialize_standalone(reader)
            self.assertFalse(result)
            self.assertFalse(manager.is_initialized)
        finally:
            os.environ.pop(_SDKSTATS_DISABLED_ENV, None)

    def test_shutdown(self):
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        reader = InMemoryMetricReader()
        manager = SdkStatsManager()
        manager.initialize_standalone(reader)
        result = manager.shutdown()
        self.assertTrue(result)
        self.assertFalse(manager.is_initialized)
        self.assertTrue(get_sdkstats_shutdown())

    def test_shutdown_when_not_initialized(self):
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        manager = SdkStatsManager()
        result = manager.shutdown()
        self.assertFalse(result)

    def test_double_initialize_is_idempotent(self):
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        reader1 = InMemoryMetricReader()
        reader2 = InMemoryMetricReader()
        manager = SdkStatsManager()
        self.assertTrue(manager.initialize_standalone(reader1))
        self.assertTrue(manager.initialize_standalone(reader2))  # Should return True (already init)

    _FAKE_STATS_CS = "InstrumentationKey=fake;" + "IngestionEndpoint=https://test.in.applicationinsights.azure.com/"

    @patch("azure.monitor.opentelemetry.exporter.export.metrics._exporter.AzureMonitorMetricExporter")
    @patch(
        "azure.monitor.opentelemetry.exporter.statsbeat._utils._get_stats_connection_string",
        return_value=_FAKE_STATS_CS,
    )
    @patch(
        "azure.monitor.opentelemetry.exporter.statsbeat._utils._get_stats_short_export_interval",
        return_value=900,
    )
    def test_initialize_uses_azure_monitor_exporter(self, mock_interval, mock_cs, mock_exporter):
        """initialize() must use AzureMonitorMetricExporter with is_sdkstats=True."""
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        manager = SdkStatsManager()
        result = manager.initialize()
        self.assertTrue(result)
        self.assertTrue(manager.is_initialized)

        mock_exporter.assert_called_once_with(
            connection_string=self._FAKE_STATS_CS,
            disable_offline_storage=True,
            is_sdkstats=True,
        )

    def test_initialize_forwards_enable_azure_monitor_flag(self):
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        manager = SdkStatsManager()
        with patch.object(manager, "_do_initialize", return_value=True) as do_initialize_mock:
            result = manager.initialize(enable_azure_monitor=True)

        self.assertTrue(result)
        do_initialize_mock.assert_called_once_with(True)

    def test_metrics_collected_after_initialize(self):
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from microsoft.opentelemetry._sdkstats._manager import SdkStatsManager

        set_sdkstats_feature(SdkStatsFeature.DISTRO)
        set_sdkstats_feature(SdkStatsFeature.A365_EXPORT)
        set_sdkstats_instrumentation(SdkStatsInstrumentation.OPENAI_V2)

        reader = InMemoryMetricReader()
        manager = SdkStatsManager()
        manager.initialize_standalone(reader)

        metrics_data = reader.get_metrics_data()
        self.assertIsNotNone(metrics_data)
        metric_names = set()
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    metric_names.add(metric.name)

        self.assertIn("feature", metric_names)
        self.assertIn("feature", metric_names)


class TestInitializeSdkStats(unittest.TestCase):
    """Tests for _initialize_sdkstats in _distro.py."""

    def setUp(self):
        _reset_state()

    def tearDown(self):
        _reset_state()

    def test_initialize_sdkstats_starts_manager_when_azure_monitor_enabled(self):
        """_initialize_sdkstats starts the distro manager regardless of AzMon — the
        two pipelines run independently so each emits its own statsbeat row."""
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        set_sdkstats_feature(SdkStatsFeature.DISTRO)
        set_sdkstats_feature(SdkStatsFeature.A365_EXPORT)

        with patch("microsoft.opentelemetry._sdkstats._manager.SdkStatsManager") as mock_cls:
            mock_manager = MagicMock()
            mock_cls.return_value = mock_manager
            _initialize_sdkstats(enable_azure_monitor=True)
            mock_manager.initialize.assert_called_once_with(True)

    def test_initialize_sdkstats_uses_manager_when_azure_monitor_disabled(self):
        """_initialize_sdkstats creates SdkStatsManager when Azure Monitor is off."""
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        set_sdkstats_feature(SdkStatsFeature.DISTRO)

        with patch("microsoft.opentelemetry._sdkstats._manager.SdkStatsManager") as mock_cls:
            mock_manager = MagicMock()
            mock_cls.return_value = mock_manager
            _initialize_sdkstats(enable_azure_monitor=False)
            mock_manager.initialize.assert_called_once_with(False)


class TestSdkStatsBridgeSetters(unittest.TestCase):
    """Tests for state bridge helper setters used by _distro bridge."""

    def setUp(self):
        _reset_state()
        try:
            from azure.monitor.opentelemetry.exporter.statsbeat._statsbeat_metrics import (
                _StatsbeatMetrics,
            )
            import azure.monitor.opentelemetry.exporter._utils as _exporter_utils

            _StatsbeatMetrics._FEATURE_ATTRIBUTES["feature"] = None
            with _exporter_utils._INSTRUMENTATIONS_BIT_MASK_LOCK:
                _exporter_utils._INSTRUMENTATIONS_BIT_MASK = 0
        except ImportError:
            pass

    def test_set_sdkstats_feature_bits_ors_into_exporter_feature_attr(self):
        from azure.monitor.opentelemetry.exporter.statsbeat._statsbeat_metrics import (
            _StatsbeatMetrics,
        )

        _StatsbeatMetrics._FEATURE_ATTRIBUTES["feature"] = 3
        set_sdkstats_feature_bits(int(SdkStatsFeature.OTLP_EXPORT))

        self.assertEqual(_StatsbeatMetrics._FEATURE_ATTRIBUTES["feature"], 3 | 256)

    def test_set_sdkstats_instrumentation_bits_ors_into_exporter_mask(self):
        import azure.monitor.opentelemetry.exporter._utils as _exporter_utils

        with _exporter_utils._INSTRUMENTATIONS_BIT_MASK_LOCK:
            _exporter_utils._INSTRUMENTATIONS_BIT_MASK = 3

        set_sdkstats_instrumentation_bits(int(SdkStatsInstrumentation.FASTAPI))


class TestRequestSuccessCallback(unittest.TestCase):
    """Tests for SdkStatsMetrics._observe_request_success_count."""

    def setUp(self):
        _reset_state()

    def test_empty_when_no_success(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        mp = MeterProvider()
        try:
            metrics = SdkStatsMetrics(mp)
            obs = list(metrics._observe_request_success_count(MagicMock()))
            self.assertEqual(obs, [])
        finally:
            mp.shutdown()

    def test_emits_one_observation_per_endpoint(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        record_success("a", "a.example")
        record_success("a", "a.example")
        record_success("b", "b.example")

        mp = MeterProvider()
        try:
            metrics = SdkStatsMetrics(mp)
            obs = list(metrics._observe_request_success_count(MagicMock()))
            self.assertEqual(len(obs), 2)
            by_endpoint = {}
            by_host = {}
            for o in obs:
                assert o.attributes is not None
                by_endpoint[o.attributes["endpoint"]] = o.value
                by_host[o.attributes["host"]] = o.value
            self.assertEqual(by_endpoint, {"a": 2, "b": 1})
            self.assertEqual(by_host, {"a.example": 2, "b.example": 1})
        finally:
            mp.shutdown()

    def test_callback_drains_count(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from microsoft.opentelemetry._sdkstats._metrics import SdkStatsMetrics

        record_success("a", "a.example")
        mp = MeterProvider()
        try:
            metrics = SdkStatsMetrics(mp)
            list(metrics._observe_request_success_count(MagicMock()))
            obs = list(metrics._observe_request_success_count(MagicMock()))
            self.assertEqual(obs, [])
        finally:
            mp.shutdown()


class TestNetworkStatsExporterWrappers(unittest.TestCase):
    """Tests for the OTLP NetworkStats* exporter decorators."""

    def setUp(self):
        _reset_state()

    def _inner_span(self, result, endpoint="https://otlp.example.com/v1/traces"):
        inner = MagicMock()
        inner._endpoint = endpoint
        inner.export.return_value = result
        return inner

    def test_span_success_records(self):
        from opentelemetry.sdk.trace.export import SpanExportResult

        wrapper = _NetworkStatsSpanExporter(self._inner_span(SpanExportResult.SUCCESS))
        self.assertEqual(wrapper.export([]), SpanExportResult.SUCCESS)
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {("otlp", "otlp.example.com"): 1})

    def test_span_failure_does_not_record(self):
        from opentelemetry.sdk.trace.export import SpanExportResult

        wrapper = _NetworkStatsSpanExporter(self._inner_span(SpanExportResult.FAILURE))
        wrapper.export([])
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {})

    def test_span_forwards_shutdown_and_force_flush(self):
        from opentelemetry.sdk.trace.export import SpanExportResult

        inner = self._inner_span(SpanExportResult.SUCCESS)
        inner.force_flush.return_value = True
        wrapper = _NetworkStatsSpanExporter(inner)
        wrapper.shutdown()
        self.assertTrue(wrapper.force_flush(1234))
        inner.shutdown.assert_called_once()
        inner.force_flush.assert_called_once_with(1234)

    def test_metric_success_records(self):
        from opentelemetry.sdk.metrics.export import MetricExportResult

        inner = MagicMock()
        inner._endpoint = "https://otlp.example.com/v1/metrics"
        inner._preferred_temporality = {}
        inner._preferred_aggregation = {}
        inner.export.return_value = MetricExportResult.SUCCESS
        wrapper = _NetworkStatsMetricExporter(inner)
        wrapper.export(MagicMock())
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {("otlp", "otlp.example.com"): 1})

    def test_metric_failure_does_not_record(self):
        from opentelemetry.sdk.metrics.export import MetricExportResult

        inner = MagicMock()
        inner._endpoint = "https://otlp.example.com/v1/metrics"
        inner._preferred_temporality = {}
        inner._preferred_aggregation = {}
        inner.export.return_value = MetricExportResult.FAILURE
        wrapper = _NetworkStatsMetricExporter(inner)
        wrapper.export(MagicMock())
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {})

    def test_log_success_records(self):
        from opentelemetry.sdk._logs.export import LogRecordExportResult

        inner = MagicMock()
        inner._endpoint = "https://otlp.example.com/v1/logs"
        inner._host = "otlp"
        inner.export.return_value = LogRecordExportResult.SUCCESS
        wrapper = _NetworkStatsLogExporter(inner)
        wrapper.export([])
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {("otlp", "otlp.example.com"): 1})

    def test_log_failure_does_not_record(self):
        from opentelemetry.sdk._logs.export import LogRecordExportResult

        inner = MagicMock()
        inner._endpoint = "https://otlp.example.com/v1/logs"
        inner.export.return_value = LogRecordExportResult.FAILURE
        wrapper = _NetworkStatsLogExporter(inner)
        wrapper.export([])
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {})


if __name__ == "__main__":
    unittest.main()
