# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from microsoft.opentelemetry.a365.core.exporters.agent365_exporter import (
    DEFAULT_CB_FAILURE_THRESHOLD,
    _Agent365Exporter,
    _CircuitBreaker,
)

# ---------------------------------------------------------------------------
# _CircuitBreaker unit tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerInit(unittest.TestCase):
    def test_starts_closed(self):
        cb = _CircuitBreaker()
        self.assertEqual(cb.state, _CircuitBreaker.CLOSED)

    def test_custom_thresholds(self):
        cb = _CircuitBreaker(failure_threshold=10, recovery_timeout=60.0)
        self.assertEqual(cb.state, _CircuitBreaker.CLOSED)
        self.assertEqual(cb.total_rejected, 0)


class TestCircuitBreakerTransitions(unittest.TestCase):
    def test_stays_closed_below_threshold(self):
        cb = _CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        self.assertEqual(cb.state, _CircuitBreaker.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_opens_at_threshold(self):
        cb = _CircuitBreaker(failure_threshold=5)
        for _ in range(5):
            cb.record_failure()
        self.assertEqual(cb.state, _CircuitBreaker.OPEN)
        self.assertFalse(cb.allow_request())

    def test_rejects_when_open(self):
        cb = _CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        self.assertFalse(cb.allow_request())
        self.assertFalse(cb.allow_request())
        self.assertEqual(cb.total_rejected, 2)

    def test_transitions_to_half_open_after_recovery_timeout(self):
        cb = _CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        cb.record_failure()
        self.assertEqual(cb.state, _CircuitBreaker.OPEN)
        # Simulate recovery timeout elapsing
        cb._last_failure_time = time.monotonic() - 31.0
        self.assertEqual(cb.state, _CircuitBreaker.HALF_OPEN)
        self.assertTrue(cb.allow_request())

    def test_half_open_success_closes(self):
        cb = _CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        cb.record_failure()
        cb._last_failure_time = time.monotonic() - 31.0
        self.assertTrue(cb.allow_request())  # half-open allows probe
        cb.record_success()
        self.assertEqual(cb.state, _CircuitBreaker.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_half_open_failure_reopens(self):
        cb = _CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        cb.record_failure()
        cb._last_failure_time = time.monotonic() - 31.0
        self.assertTrue(cb.allow_request())  # half-open probe
        cb.record_failure()
        self.assertEqual(cb.state, _CircuitBreaker.OPEN)
        self.assertFalse(cb.allow_request())

    def test_half_open_allows_only_one_probe(self):
        cb = _CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        cb.record_failure()
        cb._last_failure_time = time.monotonic() - 31.0
        # First call gets the probe token
        self.assertTrue(cb.allow_request())
        # Second call should be rejected while probe is in flight
        self.assertFalse(cb.allow_request())
        self.assertEqual(cb.total_rejected, 1)

    def test_success_resets_failure_count(self):
        cb = _CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # After reset, need 3 more failures to trip
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, _CircuitBreaker.CLOSED)
        cb.record_failure()
        self.assertEqual(cb.state, _CircuitBreaker.OPEN)

    def test_total_rejected_resets_on_close(self):
        cb = _CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        cb.record_failure()
        cb.allow_request()  # rejected
        cb.allow_request()  # rejected
        self.assertEqual(cb.total_rejected, 2)
        cb._last_failure_time = time.monotonic() - 31.0
        cb.allow_request()  # half-open probe allowed
        cb.record_success()
        self.assertEqual(cb.total_rejected, 0)


# ---------------------------------------------------------------------------
# Integration: _Agent365Exporter with circuit breaker
# ---------------------------------------------------------------------------


def _make_span(
    tenant_id="t1",
    agent_id="a1",
    name="test_span",
    trace_id=0x1234,
    span_id=0x5678,
    operation_name="invoke_agent",
):
    span = MagicMock()
    span.name = name
    attrs = {
        "microsoft.tenant.id": tenant_id,
        "gen_ai.agent.id": agent_id,
    }
    if operation_name is not None:
        attrs["gen_ai.operation.name"] = operation_name
    span.attributes = attrs

    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.span_id = span_id
    span.context = ctx
    span.get_span_context.return_value = ctx

    span.parent = None
    span.kind = SpanKind.INTERNAL
    span.start_time = 1000000000
    span.end_time = 2000000000

    status = MagicMock()
    status.status_code = StatusCode.OK
    status.description = ""
    span.status = status

    span.events = []
    span.links = []

    scope = MagicMock()
    scope.name = "test_scope"
    scope.version = "1.0"
    span.instrumentation_scope = scope

    resource = MagicMock()
    resource.attributes = {"service.name": "test-service"}
    span.resource = resource

    return span


class TestExporterCircuitBreakerIntegration(unittest.TestCase):
    """Verify that _Agent365Exporter honours the circuit breaker."""

    @patch.dict(os.environ, {}, clear=True)
    def _make_exporter(self):
        return _Agent365Exporter(token_resolver=lambda a, t: "token")

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep")
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.requests.Session")
    @patch.dict(os.environ, {}, clear=True)
    def test_circuit_opens_after_consecutive_500s(self, mock_session_cls, mock_sleep):
        """After DEFAULT_CB_FAILURE_THRESHOLD export cycles all returning 500,
        subsequent exports should be rejected without HTTP calls."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.headers = {}

        session_instance = MagicMock()
        session_instance.post.return_value = mock_resp
        mock_session_cls.return_value = session_instance

        exporter = self._make_exporter()
        exporter._session = session_instance

        span = _make_span()

        # Each failed export cycle = 1 circuit breaker failure
        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD):
            result = exporter.export([span])
            self.assertEqual(result, SpanExportResult.FAILURE)

        # Circuit should now be open
        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.OPEN)

        # Next export should fail immediately without HTTP
        session_instance.post.reset_mock()
        result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.FAILURE)
        session_instance.post.assert_not_called()

        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep")
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.requests.Session")
    @patch.dict(os.environ, {}, clear=True)
    def test_circuit_recovers_after_success(self, mock_session_cls, mock_sleep):
        """After the circuit opens and recovery timeout elapses, a successful
        probe should close the circuit."""
        mock_fail_resp = MagicMock()
        mock_fail_resp.status_code = 503
        mock_fail_resp.text = "Service Unavailable"
        mock_fail_resp.headers = {}

        mock_ok_resp = MagicMock()
        mock_ok_resp.status_code = 200
        mock_ok_resp.text = "OK"
        mock_ok_resp.headers = {}

        session_instance = MagicMock()
        mock_session_cls.return_value = session_instance

        exporter = self._make_exporter()
        exporter._session = session_instance
        exporter._circuit_breaker._recovery_timeout = 30.0

        span = _make_span()

        # Trip the circuit
        session_instance.post.return_value = mock_fail_resp
        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD):
            exporter.export([span])

        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.OPEN)

        # Simulate recovery timeout elapsing by backdating _last_failure_time
        exporter._circuit_breaker._last_failure_time = time.monotonic() - 31.0

        # Next call should be a probe (half-open) — make it succeed
        session_instance.post.return_value = mock_ok_resp
        result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.SUCCESS)
        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.CLOSED)

        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep")
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.requests.Session")
    @patch.dict(os.environ, {}, clear=True)
    def test_circuit_reopens_on_failed_probe(self, mock_session_cls, mock_sleep):
        """If the half-open probe fails, the circuit re-opens."""
        mock_fail_resp = MagicMock()
        mock_fail_resp.status_code = 500
        mock_fail_resp.text = "Error"
        mock_fail_resp.headers = {}

        session_instance = MagicMock()
        session_instance.post.return_value = mock_fail_resp
        mock_session_cls.return_value = session_instance

        exporter = self._make_exporter()
        exporter._session = session_instance
        exporter._circuit_breaker._recovery_timeout = 30.0

        span = _make_span()

        # Trip the circuit
        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD):
            exporter.export([span])

        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.OPEN)

        # Simulate recovery timeout elapsing
        exporter._circuit_breaker._last_failure_time = time.monotonic() - 31.0

        # Probe should fail, re-opening the circuit
        result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.FAILURE)
        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.OPEN)

        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep")
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.requests.Session")
    @patch.dict(os.environ, {}, clear=True)
    def test_non_retryable_errors_do_not_trip_circuit(self, mock_session_cls, mock_sleep):
        """Non-retryable 4xx errors (e.g. 401, 403) should not count toward
        the circuit breaker threshold — they indicate config problems, not
        transient endpoint failures."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.headers = {}

        session_instance = MagicMock()
        session_instance.post.return_value = mock_resp
        mock_session_cls.return_value = session_instance

        exporter = self._make_exporter()
        exporter._session = session_instance

        span = _make_span()

        # Non-retryable errors should NOT trip the circuit breaker
        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD + 2):
            exporter.export([span])

        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.CLOSED)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep")
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.requests.Session")
    @patch.dict(os.environ, {}, clear=True)
    def test_network_errors_trip_circuit(self, mock_session_cls, mock_sleep):
        """Network-level failures (RequestException) count toward the circuit breaker."""
        import requests as req

        session_instance = MagicMock()
        session_instance.post.side_effect = req.ConnectionError("connection refused")
        mock_session_cls.return_value = session_instance

        exporter = self._make_exporter()
        exporter._session = session_instance

        span = _make_span()

        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD):
            exporter.export([span])

        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.OPEN)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep")
    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.requests.Session")
    @patch.dict(os.environ, {}, clear=True)
    def test_success_between_failures_resets_circuit(self, mock_session_cls, mock_sleep):
        """A successful POST mid-stream should reset the failure counter."""
        mock_fail_resp = MagicMock()
        mock_fail_resp.status_code = 500
        mock_fail_resp.text = "Error"
        mock_fail_resp.headers = {}

        mock_ok_resp = MagicMock()
        mock_ok_resp.status_code = 200
        mock_ok_resp.text = "OK"
        mock_ok_resp.headers = {}

        session_instance = MagicMock()
        mock_session_cls.return_value = session_instance

        exporter = self._make_exporter()
        exporter._session = session_instance

        span = _make_span()

        # Fail 4 times (threshold is 5)
        session_instance.post.return_value = mock_fail_resp
        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD - 1):
            exporter.export([span])
        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.CLOSED)

        # Succeed once — resets counter
        session_instance.post.return_value = mock_ok_resp
        exporter.export([span])
        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.CLOSED)

        # Fail 4 more times — circuit should still be closed
        session_instance.post.return_value = mock_fail_resp
        for _ in range(DEFAULT_CB_FAILURE_THRESHOLD - 1):
            exporter.export([span])
        self.assertEqual(exporter._circuit_breaker.state, _CircuitBreaker.CLOSED)

        exporter.shutdown()


if __name__ == "__main__":
    unittest.main()
