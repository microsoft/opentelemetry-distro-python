# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from microsoft.opentelemetry.a365.core.exporters.agent365_exporter import (
    _Agent365Exporter,
)
from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
)


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


def make_exporter(token_resolver=None, **kwargs):
    """Build an exporter with durable delivery disabled by default.

    Durable delivery is disabled so tests do not create a real on-disk queue
    or spawn a replay thread. Durability-specific tests opt back in by setting
    ``exporter._storage`` (or passing ``enable_durable_delivery=True``).
    """
    if token_resolver is None and "contextual_token_resolver" not in kwargs:
        token_resolver = lambda a, t: "token"  # noqa: E731
    kwargs.setdefault("enable_durable_delivery", False)
    return _Agent365Exporter(token_resolver=token_resolver, **kwargs)


def _delivered():
    return DeliveryResult(DeliveryDisposition.DELIVERED)


def _permanent():
    return DeliveryResult(DeliveryDisposition.PERMANENT)


def _retryable(retry_after=None):
    return DeliveryResult(DeliveryDisposition.RETRYABLE, retry_after)


class TestAgent365ExporterInit(unittest.TestCase):
    def test_raises_on_none_resolver(self):
        with self.assertRaises(ValueError):
            _Agent365Exporter(token_resolver=None)

    def test_raises_on_zero_max_payload_bytes(self):
        with self.assertRaises(ValueError):
            _Agent365Exporter(token_resolver=lambda a, t: "token", max_payload_bytes=0)

    def test_raises_on_negative_max_payload_bytes(self):
        with self.assertRaises(ValueError):
            _Agent365Exporter(token_resolver=lambda a, t: "token", max_payload_bytes=-1)

    def test_creates_with_valid_resolver(self):
        exporter = make_exporter()
        self.assertIsNotNone(exporter)
        exporter.shutdown()


class TestAgent365ExporterExport(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_export_success(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        result = exporter.export([_make_span()])
        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter._post_once.assert_called_once()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_failure(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_permanent())
        result = exporter.export([_make_span()])
        self.assertEqual(result, SpanExportResult.FAILURE)
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_no_identity_spans(self):
        exporter = make_exporter()
        span = MagicMock()
        span.attributes = {}
        result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_after_shutdown(self):
        exporter = make_exporter()
        exporter.shutdown()
        result = exporter.export([_make_span()])
        self.assertEqual(result, SpanExportResult.FAILURE)

    @patch.dict(os.environ, {}, clear=True)
    def test_export_partitions_by_identity(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        s1 = _make_span(tenant_id="t1", agent_id="a1")
        s2 = _make_span(tenant_id="t2", agent_id="a2")
        result = exporter.export([s1, s2])
        self.assertEqual(result, SpanExportResult.SUCCESS)
        self.assertEqual(exporter._post_once.call_count, 2)
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_token_resolver_called_with_agent_tenant(self):
        resolver = MagicMock(return_value="token123")
        exporter = make_exporter(token_resolver=resolver)
        exporter._post_once = MagicMock(return_value=_delivered())
        exporter.export([_make_span(tenant_id="my_tenant", agent_id="my_agent")])
        resolver.assert_called_once_with("my_agent", "my_tenant")
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_token_resolution_failure_without_storage_is_failure(self):
        resolver = MagicMock(side_effect=Exception("auth error"))
        exporter = make_exporter(token_resolver=resolver)
        exporter._post_once = MagicMock()
        result = exporter.export([_make_span()])
        self.assertEqual(result, SpanExportResult.FAILURE)
        exporter._post_once.assert_not_called()
        exporter.shutdown()

    @patch.dict(os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": "https://custom.host.com"})
    def test_domain_override(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        exporter.export([_make_span()])
        url_arg = exporter._post_once.call_args[0][0]
        self.assertIn("custom.host.com", url_arg)
        exporter.shutdown()


class TestAgent365ExporterBuildRequest(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_build_export_request_structure(self):
        exporter = make_exporter()
        span = _make_span()
        mapped_spans = exporter._map_and_truncate_spans([span])
        resource_attrs = exporter._get_resource_attributes([span])
        payload = exporter._build_envelope(mapped_spans, resource_attrs)
        self.assertIn("resourceSpans", payload)
        resource_spans = payload["resourceSpans"]
        self.assertEqual(len(resource_spans), 1)
        self.assertIn("scopeSpans", resource_spans[0])
        self.assertIn("resource", resource_spans[0])
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_map_span_basic_fields(self):
        exporter = make_exporter()
        span = _make_span(name="my_span")
        mapped = exporter._map_span(span)
        self.assertEqual(mapped["name"], "my_span")
        self.assertIn("traceId", mapped)
        self.assertIn("spanId", mapped)
        self.assertIn("status", mapped)
        self.assertIn("startTimeUnixNano", mapped)
        self.assertIn("endTimeUnixNano", mapped)
        exporter.shutdown()


class TestAgent365ExporterForceFlush(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_force_flush_returns_true(self):
        exporter = make_exporter()
        self.assertTrue(exporter.force_flush())
        exporter.shutdown()


class TestAgent365ExporterShutdown(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_double_shutdown_safe(self):
        exporter = make_exporter()
        exporter.shutdown()
        exporter.shutdown()  # should not raise

    @patch.dict(os.environ, {}, clear=True)
    def test_shutdown_closes_replay_storage_and_session_once(self):
        exporter = make_exporter()
        replay = MagicMock()
        storage = MagicMock()
        session = MagicMock()
        exporter._replay = replay
        exporter._storage = storage
        exporter._session = session

        exporter.shutdown()
        exporter.shutdown()

        replay.shutdown.assert_called_once()
        storage.close.assert_called_once()
        session.close.assert_called_once()


class TestAgent365ExporterS2S(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_s2s_endpoint_url(self):
        exporter = make_exporter(use_s2s_endpoint=True)
        exporter._post_once = MagicMock(return_value=_delivered())
        exporter.export([_make_span()])
        url_arg = exporter._post_once.call_args[0][0]
        self.assertIn("/observabilityService/", url_arg)
        exporter.shutdown()


class TestAgent365ExporterFiltering(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_export_no_eligible_spans_logs_info(self):
        exporter = make_exporter()
        span = MagicMock()
        span.attributes = {}
        with patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.logger") as mock_logger:
            result = exporter.export([span])
        self.assertEqual(result, SpanExportResult.SUCCESS)
        mock_logger.info.assert_called_with("No eligible genAI spans to export; nothing exported.")
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_filters_out_non_genai_spans(self):
        """Spans without a known gen_ai.operation.name are filtered out."""
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        genai_span = _make_span(name="genai_span", trace_id=1, span_id=2)
        no_op_span = _make_span(name="http_span", trace_id=3, span_id=4, operation_name=None)
        unknown_op_span = _make_span(name="db_span", trace_id=5, span_id=6, operation_name="some_random_op")

        result = exporter.export([genai_span, no_op_span, unknown_op_span])

        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter._post_once.assert_called_once()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_filters_out_only_non_genai_spans_returns_success(self):
        """When all spans are filtered out, export returns SUCCESS without HTTP call."""
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        spans = [
            _make_span(name="http_span", operation_name=None),
            _make_span(name="db_span", operation_name="other"),
        ]

        result = exporter.export(spans)

        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter._post_once.assert_not_called()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_includes_inference_operation_type_chat_spans(self):
        """Spans with InferenceOperationType.CHAT value ('Chat') are kept without normalization."""
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        chat_span = _make_span(name="chat_span", trace_id=1, span_id=2, operation_name="Chat")

        result = exporter.export([chat_span])

        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter._post_once.assert_called_once()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_filters_out_unsupported_inference_operation_types(self):
        """Spans with TextCompletion / GenerateContent are filtered out."""
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        text_completion_span = _make_span(
            name="text_completion_span", trace_id=3, span_id=4, operation_name="TextCompletion"
        )
        generate_content_span = _make_span(
            name="generate_content_span", trace_id=5, span_id=6, operation_name="GenerateContent"
        )

        result = exporter.export([text_completion_span, generate_content_span])

        self.assertEqual(result, SpanExportResult.SUCCESS)
        exporter._post_once.assert_not_called()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_export_does_not_normalize_canonical_operation_names(self):
        """invoke_agent / execute_tool / output_messages / chat are not rewritten."""
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_delivered())
        for op in ("invoke_agent", "execute_tool", "output_messages", "chat"):
            with self.subTest(operation_name=op):
                exporter._post_once.reset_mock()
                span = _make_span(name=f"{op}_span", trace_id=1, span_id=2, operation_name=op)
                result = exporter.export([span])
                self.assertEqual(result, SpanExportResult.SUCCESS)
                exporter._post_once.assert_called_once()
        exporter.shutdown()


# ---------------------------------------------------------------------------
# Durable delivery integration (classified single-send + storage + gate).
# ---------------------------------------------------------------------------


class TestAgent365ExporterDurableDelivery(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_retryable_failure_returns_success_when_payload_is_stored(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_retryable(30))
        exporter._storage = MagicMock()
        exporter._storage.store.return_value = True
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.SUCCESS)
        exporter._storage.store.assert_called_once()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_retryable_failure_returns_failure_when_storage_unavailable(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_retryable(30))
        exporter._storage = MagicMock()
        exporter._storage.store.return_value = False
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.FAILURE)
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_retryable_failure_is_failure_when_storage_disabled(self):
        # Durable delivery disabled => _storage is None => must surface failure.
        exporter = make_exporter()
        self.assertIsNone(exporter._storage)
        exporter._post_once = MagicMock(return_value=_retryable(30))
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.FAILURE)
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_permanent_failure_is_not_stored(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_permanent())
        exporter._storage = MagicMock()
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.FAILURE)
        exporter._storage.store.assert_not_called()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_token_resolver_exception_is_stored_and_returns_success(self):
        resolver = MagicMock(side_effect=Exception("auth error"))
        exporter = make_exporter(token_resolver=resolver)
        exporter._post_once = MagicMock()
        exporter._storage = MagicMock()
        exporter._storage.store.return_value = True
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.SUCCESS)
        exporter._storage.store.assert_called_once()
        exporter._post_once.assert_not_called()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_empty_token_is_permanent_and_not_sent_or_stored(self):
        exporter = make_exporter(token_resolver=lambda a, t: None)
        exporter._post_once = MagicMock()
        exporter._storage = MagicMock()
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.FAILURE)
        exporter._post_once.assert_not_called()
        exporter._storage.store.assert_not_called()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_gate_rejection_persists_without_sending(self):
        exporter = make_exporter()
        exporter._gate = MagicMock()
        exporter._gate.try_acquire.return_value = False
        exporter._post_once = MagicMock()
        exporter._storage = MagicMock()
        exporter._storage.store.return_value = True
        self.assertIs(exporter.export([_make_span()]), SpanExportResult.SUCCESS)
        exporter._post_once.assert_not_called()
        exporter._storage.store.assert_called_once()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_successful_persistence_wakes_replay(self):
        exporter = make_exporter()
        exporter._post_once = MagicMock(return_value=_retryable(30))
        exporter._storage = MagicMock()
        exporter._storage.store.return_value = True
        exporter._replay = MagicMock()
        exporter.export([_make_span()])
        exporter._replay.wake.assert_called()
        exporter.shutdown()


# ---------------------------------------------------------------------------
# Network statsbeat — recorded inside the classified single-send _post_once.
# ---------------------------------------------------------------------------


def _make_response(status_code, headers=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    return resp


class TestNetworkStatsbeatHook(unittest.TestCase):
    URL = "https://agent365.svc.cloud.microsoft/api/v1/spans"
    HOST = "agent365.svc.cloud.microsoft"
    ENDPOINT = "a365"

    def setUp(self):
        from microsoft.opentelemetry._sdkstats._utils import reset_all

        reset_all()

    def tearDown(self):
        from microsoft.opentelemetry._sdkstats._utils import reset_all

        reset_all()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_success_records_success(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_SUCCESS_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(200)
        result = exporter._post_once(self.URL, "{}", {})
        self.assertIs(result.disposition, DeliveryDisposition.DELIVERED)
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {(self.ENDPOINT, self.HOST): 1})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_non_2xx_does_not_record_success(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_SUCCESS_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(404)
        exporter._post_once(self.URL, "{}", {})
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=False)
    def test_disabled_does_not_record(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_SUCCESS_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(200)
        exporter._post_once(self.URL, "{}", {})
        self.assertEqual(drain(REQUEST_SUCCESS_NAME), {})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_success_records_duration(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_DURATION_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(200)
        exporter._post_once(self.URL, "{}", {})

        snap = drain(REQUEST_DURATION_NAME)
        self.assertEqual(set(snap.keys()), {(self.ENDPOINT, self.HOST)})
        total_seconds, count = snap[(self.ENDPOINT, self.HOST)]
        self.assertEqual(count, 1)
        self.assertGreaterEqual(total_seconds, 0)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_permanent_status_records_failure(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_FAILURE_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(400)
        result = exporter._post_once(self.URL, "{}", {})
        self.assertIs(result.disposition, DeliveryDisposition.PERMANENT)
        self.assertEqual(drain(REQUEST_FAILURE_NAME), {(self.ENDPOINT, self.HOST, 400): 1})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_throttle_status_records_throttle(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_THROTTLE_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(402)
        result = exporter._post_once(self.URL, "{}", {})
        self.assertIs(result.disposition, DeliveryDisposition.PERMANENT)
        self.assertEqual(drain(REQUEST_THROTTLE_NAME), {(self.ENDPOINT, self.HOST, 402): 1})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_retryable_5xx_records_retry(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_RETRY_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(503)
        result = exporter._post_once(self.URL, "{}", {})
        self.assertIs(result.disposition, DeliveryDisposition.RETRYABLE)
        self.assertEqual(drain(REQUEST_RETRY_NAME), {(self.ENDPOINT, self.HOST, 503): 1})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_retryable_401_records_retry(self, _enabled):
        from microsoft.opentelemetry._sdkstats._utils import REQUEST_RETRY_NAME, drain

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(401)
        result = exporter._post_once(self.URL, "{}", {})
        self.assertIs(result.disposition, DeliveryDisposition.RETRYABLE)
        self.assertEqual(drain(REQUEST_RETRY_NAME), {(self.ENDPOINT, self.HOST, 401): 1})
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_retry_after_header_is_parsed_without_sleeping(self, _enabled):
        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(429, headers={"Retry-After": "42"})
        with patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.time.sleep") as mock_sleep:
            result = exporter._post_once(self.URL, "{}", {})
        self.assertIs(result.disposition, DeliveryDisposition.RETRYABLE)
        self.assertEqual(result.retry_after, 42.0)
        mock_sleep.assert_not_called()
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=True)
    def test_request_exception_records_exception_and_duration(self, _enabled):
        import requests

        from microsoft.opentelemetry._sdkstats._utils import (
            REQUEST_DURATION_NAME,
            REQUEST_EXCEPTION_NAME,
            drain,
        )

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.side_effect = requests.ConnectionError("boom")
        result = exporter._post_once(self.URL, "{}", {})

        self.assertIs(result.disposition, DeliveryDisposition.RETRYABLE)
        # Single send => exception recorded exactly once.
        self.assertEqual(
            drain(REQUEST_EXCEPTION_NAME),
            {(self.ENDPOINT, self.HOST, "ConnectionError"): 1},
        )
        snap = drain(REQUEST_DURATION_NAME)
        self.assertEqual(set(snap.keys()), {(self.ENDPOINT, self.HOST)})
        _total, count = snap[(self.ENDPOINT, self.HOST)]
        self.assertEqual(count, 1)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=False)
    def test_403_insufficient_scope_logs_actionable_message(self, _enabled):
        """HTTP 403 with insufficient_scope logs an actionable message with doc links."""
        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(
            403,
            headers={
                "www-authenticate": (
                    'Bearer error="insufficient_scope", '
                    'error_description="Required app role: Agent365.Observability.OtelWrite", '
                    'scope="Agent365.Observability.OtelWrite"'
                ),
                "x-ms-correlation-id": "test-correlation-id",
            },
        )
        with self.assertLogs("microsoft.opentelemetry.a365.core.exporters.agent365_exporter", level="ERROR") as log:
            result = exporter._post_once(self.URL, "{}", {})

        self.assertIs(result.disposition, DeliveryDisposition.PERMANENT)
        self.assertEqual(len(log.output), 1)
        msg = log.output[0]
        self.assertIn("Agent365.Observability.OtelWrite", msg)
        self.assertIn("https://aka.ms/a365-403", msg)
        self.assertIn("https://aka.ms/foundry-grant-agent-365-permissions", msg)
        self.assertIn("Foundry", msg)
        exporter.shutdown()

    @patch("microsoft.opentelemetry.a365.core.exporters.agent365_exporter.is_sdkstats_enabled", return_value=False)
    def test_disabled_records_no_metrics(self, _enabled):
        """When sdkstats is disabled, none of the helpers fire."""
        from microsoft.opentelemetry._sdkstats._utils import (
            REQUEST_DURATION_NAME,
            REQUEST_FAILURE_NAME,
            REQUEST_RETRY_NAME,
            REQUEST_THROTTLE_NAME,
            drain,
        )

        exporter = make_exporter()
        exporter._session = MagicMock()
        exporter._session.post.return_value = _make_response(503)
        exporter._post_once(self.URL, "{}", {})

        self.assertEqual(drain(REQUEST_DURATION_NAME), {})
        self.assertEqual(drain(REQUEST_FAILURE_NAME), {})
        self.assertEqual(drain(REQUEST_RETRY_NAME), {})
        self.assertEqual(drain(REQUEST_THROTTLE_NAME), {})
        exporter.shutdown()


if __name__ == "__main__":
    unittest.main()
