# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Transmission-gate coverage.

The legacy global ``_CircuitBreaker`` was removed in favour of the
per-identity :class:`TransmissionGate`.  Its half-open / probe behaviour now
lives on the gate, so the circuit-breaker tests were migrated here to cover the
gate directly and to verify that the exporter honours it (a blocked identity
persists instead of sending, and a single probe is admitted once the block
window elapses).
"""

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
    IdentityKey,
    TransmissionGate,
)


class FakeClock:
    """Callable monotonic clock used to drive the gate deterministically."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


KEY = IdentityKey(tenant_id="t1", agent_id="a1", agentic_user_id=None, use_s2s_endpoint=False)
OTHER_KEY = IdentityKey(tenant_id="t2", agent_id="a2", agentic_user_id=None, use_s2s_endpoint=False)


# ---------------------------------------------------------------------------
# TransmissionGate unit tests (half-open probe behaviour).
# ---------------------------------------------------------------------------


class TestTransmissionGate(unittest.TestCase):
    def _gate(self, clock=None):
        return TransmissionGate(clock=clock or FakeClock(), random_fn=lambda: 0.0)

    def test_allows_first_send(self):
        self.assertTrue(self._gate().try_acquire(KEY))

    def test_blocks_after_retryable_failure(self):
        clock = FakeClock()
        gate = self._gate(clock)
        gate.record_retryable_failure(KEY, retry_after=30)
        self.assertFalse(gate.try_acquire(KEY))

    def test_allows_single_probe_after_block_window(self):
        clock = FakeClock()
        gate = self._gate(clock)
        gate.record_retryable_failure(KEY, retry_after=30)
        clock.advance(30)
        # Exactly one probe is admitted; a concurrent second acquire is refused.
        self.assertTrue(gate.try_acquire(KEY))
        self.assertFalse(gate.try_acquire(KEY))

    def test_success_resets_block(self):
        clock = FakeClock()
        gate = self._gate(clock)
        gate.record_retryable_failure(KEY, retry_after=30)
        clock.advance(30)
        self.assertTrue(gate.try_acquire(KEY))  # probe
        gate.record_success(KEY)
        self.assertTrue(gate.try_acquire(KEY))  # fully reset

    def test_failed_probe_reblocks(self):
        clock = FakeClock()
        gate = self._gate(clock)
        gate.record_retryable_failure(KEY, retry_after=30)
        clock.advance(30)
        self.assertTrue(gate.try_acquire(KEY))  # probe admitted
        gate.record_retryable_failure(KEY, retry_after=30)  # probe failed
        self.assertFalse(gate.try_acquire(KEY))

    def test_release_probe_allows_reacquire(self):
        gate = self._gate()
        self.assertTrue(gate.try_acquire(KEY))
        gate.release_probe(KEY)
        self.assertTrue(gate.try_acquire(KEY))

    def test_isolates_identities(self):
        gate = self._gate()
        gate.record_retryable_failure(KEY, retry_after=30)
        self.assertFalse(gate.try_acquire(KEY))
        self.assertTrue(gate.try_acquire(OTHER_KEY))


# ---------------------------------------------------------------------------
# Exporter integration: the gate governs sending vs. persisting.
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


class TestExporterGateIntegration(unittest.TestCase):
    def _make_exporter(self, clock):
        exporter = _Agent365Exporter(
            token_resolver=lambda a, t: "token",
            enable_durable_delivery=False,
        )
        exporter._gate = TransmissionGate(clock=clock, random_fn=lambda: 0.0)
        exporter._storage = MagicMock()
        exporter._storage.store.return_value = True
        return exporter

    @patch.dict(os.environ, {}, clear=True)
    def test_retryable_blocks_gate_then_subsequent_export_persists_without_send(self):
        clock = FakeClock()
        exporter = self._make_exporter(clock)
        exporter._post_once = MagicMock(return_value=DeliveryResult(DeliveryDisposition.RETRYABLE, 30))
        span = _make_span()

        # First export: one send, retryable => persisted, gate blocked.
        self.assertIs(exporter.export([span]), SpanExportResult.SUCCESS)
        self.assertEqual(exporter._post_once.call_count, 1)

        # Second export while blocked: gate rejects => persisted, no send.
        exporter._post_once.reset_mock()
        exporter._storage.store.reset_mock()
        self.assertIs(exporter.export([span]), SpanExportResult.SUCCESS)
        exporter._post_once.assert_not_called()
        exporter._storage.store.assert_called_once()
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_probe_admitted_after_block_window_elapses(self):
        clock = FakeClock()
        exporter = self._make_exporter(clock)
        exporter._post_once = MagicMock(return_value=DeliveryResult(DeliveryDisposition.RETRYABLE, 30))
        span = _make_span()

        exporter.export([span])  # block gate
        clock.advance(30)

        exporter._post_once.reset_mock()
        exporter._post_once.return_value = DeliveryResult(DeliveryDisposition.DELIVERED)
        exporter._storage.store.reset_mock()
        self.assertIs(exporter.export([span]), SpanExportResult.SUCCESS)
        exporter._post_once.assert_called_once()  # probe sent
        exporter._storage.store.assert_not_called()  # delivered => no persist
        exporter.shutdown()

    @patch.dict(os.environ, {}, clear=True)
    def test_block_is_isolated_to_failing_identity(self):
        clock = FakeClock()
        exporter = self._make_exporter(clock)
        exporter._post_once = MagicMock(return_value=DeliveryResult(DeliveryDisposition.RETRYABLE, 30))

        exporter.export([_make_span(tenant_id="t1", agent_id="a1")])  # block a1

        exporter._post_once.reset_mock()
        exporter._post_once.return_value = DeliveryResult(DeliveryDisposition.DELIVERED)
        self.assertIs(
            exporter.export([_make_span(tenant_id="t2", agent_id="a2")]),
            SpanExportResult.SUCCESS,
        )
        exporter._post_once.assert_called_once()  # a2 unaffected by a1's block
        exporter.shutdown()


if __name__ == "__main__":
    unittest.main()
