# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Tests for the _sdkstats package — state, bridge, network metrics, and
the distro-level ``_initialize_sdkstats`` orchestration."""

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
    REQUEST_DURATION_NAME,
    REQUEST_EXCEPTION_NAME,
    REQUEST_FAILURE_NAME,
    REQUEST_RETRY_NAME,
    REQUEST_SUCCESS_NAME,
    REQUEST_THROTTLE_NAME,
    THROTTLE_STATUS_CODES,
    drain,
    record_duration,
    record_exception,
    record_failure,
    record_retry,
    record_success,
    record_throttle,
    reset_all,
)
# Network sdkstats wrappers are temporarily disabled. See
# microsoft/opentelemetry/_sdkstats/_otlp_wrapper.py.
# from microsoft.opentelemetry._sdkstats._otlp_wrapper import (
#     _NetworkStatsLogExporter,
#     _NetworkStatsMetricExporter,
#     _NetworkStatsSpanExporter,
# )


def _reset_state():
    """Reset module-level state between tests."""
    with _STATE_LOCK:
        _SDKSTATS_STATE["SHUTDOWN"] = False
        _SDKSTATS_STATE["FEATURE_FLAGS"] = SdkStatsFeature.NONE
        _SDKSTATS_STATE["INSTRUMENTATION_FLAGS"] = SdkStatsInstrumentation.NONE
    reset_all()


def _reset_upstream_singleton():
    """Reset the upstream StatsbeatManager singleton between tests."""
    try:
        from azure.monitor.opentelemetry.exporter.statsbeat._manager import (
            StatsbeatManager,
        )
        from azure.monitor.opentelemetry.exporter._utils import Singleton
    except ImportError:
        return

    try:
        StatsbeatManager().shutdown()
    except Exception:  # pylint: disable=broad-except
        pass
    instances = getattr(Singleton, "_instances", None)
    if isinstance(instances, dict):
        instances.pop(StatsbeatManager, None)


def _reset_network_metrics_guard():
    from microsoft.opentelemetry._sdkstats import _network_metrics

    _network_metrics._reset_for_tests()


class TestSdkStatsEnabled(unittest.TestCase):
    def setUp(self):
        _reset_state()
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
        for name, flag in _INSTRUMENTATION_NAME_MAP.items():
            self.assertNotEqual(flag, 0, f"Flag for {name} is zero")


class TestSdkStatsThreadSafety(unittest.TestCase):
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

        expected = SdkStatsFeature.NONE
        for f in flags:
            expected |= f
        self.assertEqual(get_sdkstats_feature_flags(), expected)


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

        with _exporter_utils._INSTRUMENTATIONS_BIT_MASK_LOCK:
            self.assertEqual(
                _exporter_utils._INSTRUMENTATIONS_BIT_MASK,
                3 | int(SdkStatsInstrumentation.FASTAPI),
            )


class TestBuildDefaultSdkStatsConfig(unittest.TestCase):
    """Tests for the default StatsbeatConfig builder."""

    def test_returns_config_with_required_fields(self):
        from microsoft.opentelemetry._sdkstats._config import (
            _build_default_sdkstats_config,
        )

        config = _build_default_sdkstats_config()
        self.assertIsNotNone(config)
        self.assertTrue(config.instrumentation_key)
        self.assertTrue(config.endpoint)
        self.assertTrue(config.region)
        self.assertTrue(config.connection_string)

    def test_passes_upstream_validation(self):
        from azure.monitor.opentelemetry.exporter.statsbeat._manager import (
            StatsbeatManager,
        )
        from microsoft.opentelemetry._sdkstats._config import (
            _build_default_sdkstats_config,
        )

        config = _build_default_sdkstats_config()
        # pylint: disable=protected-access
        self.assertTrue(StatsbeatManager._validate_config(config))


class TestNetworkMetricsRegistration(unittest.TestCase):
    """Tests for register_network_gauges() idempotency and behaviour."""

    def setUp(self):
        _reset_state()
        _reset_upstream_singleton()
        _reset_network_metrics_guard()

    def tearDown(self):
        _reset_upstream_singleton()
        _reset_network_metrics_guard()

    def test_returns_false_when_manager_has_no_meter_provider(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            register_network_gauges,
        )

        self.assertFalse(register_network_gauges())

    def test_returns_true_then_false_on_repeat(self):
        from azure.monitor.opentelemetry.exporter.statsbeat._manager import (
            StatsbeatManager,
        )
        from microsoft.opentelemetry._sdkstats._config import (
            _build_default_sdkstats_config,
        )
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            register_network_gauges,
        )

        config = _build_default_sdkstats_config()
        self.assertTrue(StatsbeatManager().initialize(config))

        self.assertTrue(register_network_gauges())
        self.assertFalse(register_network_gauges())


class TestObserveRequestSuccessCount(unittest.TestCase):
    """Tests for the network gauge callback."""

    def setUp(self):
        _reset_state()

    def test_empty_when_no_success(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_success_count,
        )

        obs = list(_observe_request_success_count(MagicMock()))
        self.assertEqual(obs, [])

    def test_emits_one_observation_per_endpoint(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_success_count,
        )

        record_success("a", "a.example")
        record_success("a", "a.example")
        record_success("b", "b.example")

        obs = list(_observe_request_success_count(MagicMock()))
        self.assertEqual(len(obs), 2)
        by_endpoint = {}
        by_host = {}
        for o in obs:
            assert o.attributes is not None
            by_endpoint[o.attributes["endpoint"]] = o.value
            by_host[o.attributes["host"]] = o.value
        self.assertEqual(by_endpoint, {"a": 2, "b": 1})
        self.assertEqual(by_host, {"a.example": 2, "b.example": 1})

    def test_callback_drains_count(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_success_count,
        )

        record_success("a", "a.example")
        list(_observe_request_success_count(MagicMock()))
        obs = list(_observe_request_success_count(MagicMock()))
        self.assertEqual(obs, [])


class TestRecordHelpers(unittest.TestCase):
    """Verify each ``record_*`` helper bumps the correct bucket / key shape."""

    def setUp(self):
        _reset_state()

    def test_record_duration_accumulates_sum_and_count(self):
        record_duration("a365", "a.example", 0.1)
        record_duration("a365", "a.example", 0.4)
        record_duration("otlp", "o.example", 0.2)

        snap = drain(REQUEST_DURATION_NAME)
        self.assertEqual(set(snap.keys()), {("a365", "a.example"), ("otlp", "o.example")})

        a_sum, a_count = snap[("a365", "a.example")]
        self.assertAlmostEqual(a_sum, 0.5)
        self.assertEqual(a_count, 2)

        o_sum, o_count = snap[("otlp", "o.example")]
        self.assertAlmostEqual(o_sum, 0.2)
        self.assertEqual(o_count, 1)

    def test_record_failure_keys_include_int_status_code(self):
        record_failure("a365", "a.example", 401)
        record_failure("a365", "a.example", 401)
        record_failure("a365", "a.example", 403)

        self.assertEqual(
            drain(REQUEST_FAILURE_NAME),
            {("a365", "a.example", 401): 2, ("a365", "a.example", 403): 1},
        )

    def test_record_retry_keys_include_int_status_code(self):
        record_retry("a365", "a.example", 429)
        record_retry("a365", "a.example", 503)

        self.assertEqual(
            drain(REQUEST_RETRY_NAME),
            {("a365", "a.example", 429): 1, ("a365", "a.example", 503): 1},
        )

    def test_record_throttle_keys_include_int_status_code(self):
        record_throttle("a365", "a.example", 402)
        record_throttle("a365", "a.example", 439)

        self.assertEqual(
            drain(REQUEST_THROTTLE_NAME),
            {("a365", "a.example", 402): 1, ("a365", "a.example", 439): 1},
        )

    def test_record_exception_keys_include_exception_type(self):
        record_exception("a365", "a.example", "ConnectionError")
        record_exception("a365", "a.example", "ConnectionError")
        record_exception("a365", "a.example", "Timeout")

        self.assertEqual(
            drain(REQUEST_EXCEPTION_NAME),
            {
                ("a365", "a.example", "ConnectionError"): 2,
                ("a365", "a.example", "Timeout"): 1,
            },
        )

    def test_throttle_status_codes_match_upstream(self):
        # Upstream owns this list; the distro re-exports it.  Guard against
        # an accidental local override.
        from azure.monitor.opentelemetry.exporter._constants import (
            _THROTTLE_STATUS_CODES,
        )

        self.assertEqual(THROTTLE_STATUS_CODES, _THROTTLE_STATUS_CODES)


class TestObserveRequestDuration(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_empty_when_no_samples(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_duration,
        )

        self.assertEqual(list(_observe_request_duration(MagicMock())), [])

    def test_emits_average_in_milliseconds(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_duration,
        )

        record_duration("a365", "a.example", 0.1)  # 100 ms
        record_duration("a365", "a.example", 0.3)  # 300 ms — avg should be 200 ms

        obs = list(_observe_request_duration(MagicMock()))
        self.assertEqual(len(obs), 1)
        o = obs[0]
        assert o.attributes is not None
        self.assertEqual(o.attributes["endpoint"], "a365")
        self.assertEqual(o.attributes["host"], "a.example")
        self.assertAlmostEqual(o.value, 200.0)

    def test_callback_drains_state(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_duration,
        )

        record_duration("a365", "a.example", 0.1)
        list(_observe_request_duration(MagicMock()))
        self.assertEqual(list(_observe_request_duration(MagicMock())), [])


class TestObserveRequestFailureCount(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_empty_when_no_failures(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_failure_count,
        )

        self.assertEqual(list(_observe_request_failure_count(MagicMock())), [])

    def test_emits_one_per_status(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_failure_count,
        )

        record_failure("a365", "a.example", 401)
        record_failure("a365", "a.example", 401)
        record_failure("a365", "a.example", 403)

        obs = list(_observe_request_failure_count(MagicMock()))
        self.assertEqual(len(obs), 2)
        by_status = {}
        for o in obs:
            assert o.attributes is not None
            self.assertEqual(o.attributes["endpoint"], "a365")
            self.assertEqual(o.attributes["host"], "a.example")
            by_status[o.attributes["statusCode"]] = o.value
        self.assertEqual(by_status, {401: 2, 403: 1})

    def test_callback_drains_state(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_failure_count,
        )

        record_failure("a365", "a.example", 401)
        list(_observe_request_failure_count(MagicMock()))
        self.assertEqual(list(_observe_request_failure_count(MagicMock())), [])


class TestObserveRequestRetryCount(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_emits_one_per_status(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_retry_count,
        )

        record_retry("a365", "a.example", 429)
        record_retry("a365", "a.example", 503)
        record_retry("a365", "a.example", 503)

        obs = list(_observe_request_retry_count(MagicMock()))
        self.assertEqual(len(obs), 2)
        by_status = {o.attributes["statusCode"]: o.value for o in obs if o.attributes}
        self.assertEqual(by_status, {429: 1, 503: 2})

    def test_callback_drains_state(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_retry_count,
        )

        record_retry("a365", "a.example", 429)
        list(_observe_request_retry_count(MagicMock()))
        self.assertEqual(list(_observe_request_retry_count(MagicMock())), [])


class TestObserveRequestThrottleCount(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_emits_one_per_status(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_throttle_count,
        )

        record_throttle("a365", "a.example", 402)
        record_throttle("a365", "a.example", 439)

        obs = list(_observe_request_throttle_count(MagicMock()))
        self.assertEqual(len(obs), 2)
        by_status = {o.attributes["statusCode"]: o.value for o in obs if o.attributes}
        self.assertEqual(by_status, {402: 1, 439: 1})

    def test_callback_drains_state(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_throttle_count,
        )

        record_throttle("a365", "a.example", 402)
        list(_observe_request_throttle_count(MagicMock()))
        self.assertEqual(list(_observe_request_throttle_count(MagicMock())), [])


class TestObserveRequestExceptionCount(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_emits_one_per_exception_type(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_exception_count,
        )

        record_exception("a365", "a.example", "ConnectionError")
        record_exception("a365", "a.example", "ConnectionError")
        record_exception("a365", "a.example", "Timeout")

        obs = list(_observe_request_exception_count(MagicMock()))
        self.assertEqual(len(obs), 2)
        by_type = {o.attributes["exceptionType"]: o.value for o in obs if o.attributes}
        self.assertEqual(by_type, {"ConnectionError": 2, "Timeout": 1})

    def test_callback_drains_state(self):
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            _observe_request_exception_count,
        )

        record_exception("a365", "a.example", "ConnectionError")
        list(_observe_request_exception_count(MagicMock()))
        self.assertEqual(list(_observe_request_exception_count(MagicMock())), [])


class TestRegisterNetworkGaugesAttachesAllSix(unittest.TestCase):
    """``register_network_gauges`` must attach a callback to every upstream
    network statsbeat gauge, not just success."""

    def setUp(self):
        _reset_state()
        _reset_upstream_singleton()
        _reset_network_metrics_guard()

    def tearDown(self):
        _reset_upstream_singleton()
        _reset_network_metrics_guard()

    def test_attaches_to_all_six_gauges(self):
        from azure.monitor.opentelemetry.exporter.statsbeat._manager import (
            StatsbeatManager,
        )
        from microsoft.opentelemetry._sdkstats._config import (
            _build_default_sdkstats_config,
        )
        from microsoft.opentelemetry._sdkstats._network_metrics import (
            register_network_gauges,
        )

        config = _build_default_sdkstats_config()
        self.assertTrue(StatsbeatManager().initialize(config))

        # The six upstream gauges the distro must attach to.
        gauge_attrs = [
            "_success_count",
            "_average_duration",
            "_failure_count",
            "_retry_count",
            "_throttle_count",
            "_exception_count",
        ]

        # Snapshot pre-registration callback counts so we can assert exactly
        # one new callback per gauge.
        metrics = StatsbeatManager()._metrics  # pylint: disable=protected-access
        assert metrics is not None
        before = {
            name: len(getattr(metrics, name)._callbacks) for name in gauge_attrs  # pylint: disable=protected-access
        }

        self.assertTrue(register_network_gauges())

        for name in gauge_attrs:
            after = len(getattr(metrics, name)._callbacks)  # pylint: disable=protected-access
            self.assertEqual(
                after,
                before[name] + 1,
                f"Expected one distro callback appended to {name}",
            )


class TestInitializeSdkStats(unittest.TestCase):
    """Tests for _initialize_sdkstats in _distro.py."""

    def setUp(self):
        _reset_state()
        _reset_upstream_singleton()
        _reset_network_metrics_guard()

    def tearDown(self):
        _reset_state()
        _reset_upstream_singleton()
        _reset_network_metrics_guard()

    def test_no_op_when_disabled(self):
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        os.environ[_SDKSTATS_DISABLED_ENV] = "true"
        try:
            with patch("azure.monitor.opentelemetry.exporter.statsbeat._manager.StatsbeatManager") as mock_cls:
                _initialize_sdkstats(enable_azure_monitor=False)
                mock_cls.assert_not_called()
        finally:
            os.environ.pop(_SDKSTATS_DISABLED_ENV, None)

    def test_azure_monitor_path_does_not_initialize_manager(self):
        """When Azure Monitor is on, the exporter already initialised the
        manager from customer config; the distro must NOT call initialize()."""
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        with patch("azure.monitor.opentelemetry.exporter.statsbeat._manager.StatsbeatManager") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            _initialize_sdkstats(enable_azure_monitor=True)
            mock_instance.initialize.assert_not_called()

    def test_standalone_path_initializes_manager_with_default_config(self):
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        with (
            patch("microsoft.opentelemetry._sdkstats._config._build_default_sdkstats_config") as mock_build,
            patch("azure.monitor.opentelemetry.exporter.statsbeat._manager.StatsbeatManager") as mock_cls,
        ):
            fake_config = MagicMock(name="StatsbeatConfig")
            mock_build.return_value = fake_config
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            _initialize_sdkstats(enable_azure_monitor=False)

            mock_build.assert_called_once_with()
            mock_instance.initialize.assert_called_once_with(fake_config)

    def test_standalone_skips_manager_when_config_is_none(self):
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        with (
            patch(
                "microsoft.opentelemetry._sdkstats._config._build_default_sdkstats_config",
                return_value=None,
            ),
            patch("azure.monitor.opentelemetry.exporter.statsbeat._manager.StatsbeatManager") as mock_cls,
        ):
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            _initialize_sdkstats(enable_azure_monitor=False)
            mock_instance.initialize.assert_not_called()

    def test_always_calls_register_network_gauges(self):
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        with (
            patch("microsoft.opentelemetry._sdkstats._network_metrics.register_network_gauges") as mock_register,
            patch("azure.monitor.opentelemetry.exporter.statsbeat._manager.StatsbeatManager"),
        ):
            _initialize_sdkstats(enable_azure_monitor=True)
            _initialize_sdkstats(enable_azure_monitor=False)
            self.assertEqual(mock_register.call_count, 2)

    def test_always_bridges_feature_and_instrumentation_bits(self):
        from microsoft.opentelemetry._distro import _initialize_sdkstats

        with (
            patch("microsoft.opentelemetry._distro._bridge_sdkstats_to_azure_monitor") as mock_bridge,
            patch("azure.monitor.opentelemetry.exporter.statsbeat._manager.StatsbeatManager"),
        ):
            _initialize_sdkstats(enable_azure_monitor=True)
            _initialize_sdkstats(enable_azure_monitor=False)
            self.assertEqual(mock_bridge.call_count, 2)


"""
class TestNetworkStatsExporterWrappers(unittest.TestCase):
    '''Tests for the OTLP NetworkStats* exporter decorators.'''

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
"""


if __name__ == "__main__":
    unittest.main()
