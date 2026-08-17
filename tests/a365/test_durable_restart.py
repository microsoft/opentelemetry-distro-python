# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Restart / durability tests.

Verify that a payload persisted by one exporter instance is replayed and
delivered by a *new* exporter instance pointed at the same storage directory,
rebuilding authentication with a freshly resolved token.  This is the crash /
process-restart scenario the durable queue exists for.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from microsoft.opentelemetry.a365.core.exporters.agent365_exporter import (
    _Agent365Exporter,
)
from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    IdentityKey,
)
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import DurableRecord


def _make_span(
    tenant_id="t1",
    agent_id="a1",
    agentic_user_id=None,
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
    if agentic_user_id is not None:
        attrs["microsoft.agent.user.id"] = agentic_user_id
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


def _queue_size(storage) -> int:
    """Count claimable records without leaving them leased."""
    claimed = storage.claim(limit=1000, lease_seconds=0.0)
    for record in claimed:
        storage.release(record.record_id)
    return len(claimed)


def test_restart_replays_persisted_record_with_fresh_token(tmp_path):
    storage_dir = tmp_path / "queue"

    # --- Instance A: a retryable send persists the payload, then shuts down. ---
    exporter_a = _Agent365Exporter(
        token_resolver=lambda a, t: "stale-token",
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    exporter_a._post_once = MagicMock(  # type: ignore[method-assign]
        return_value=DeliveryResult(DeliveryDisposition.RETRYABLE, 30)
    )

    assert exporter_a.export([_make_span(agentic_user_id="user-9")]) is SpanExportResult.SUCCESS
    assert _queue_size(exporter_a._storage) == 1
    exporter_a.shutdown()

    # --- Instance B: fresh process, same directory, fresh token. ---
    captured = {}

    def fresh_resolver(agent_id, tenant_id):
        return "fresh-token"

    exporter_b = _Agent365Exporter(
        token_resolver=fresh_resolver,
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    # Bring up storage + replay coordinator without starting the background
    # thread, so replay can be driven deterministically from the test.
    exporter_b._ensure_durable_initialized()

    def fake_post_once(url, body, headers):
        captured["authorization"] = headers.get("authorization")
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    exporter_b._post_once = fake_post_once  # type: ignore[method-assign]

    # The leftover record is claimed, re-authenticated, delivered, and removed.
    exporter_b._replay.run_once()

    assert _queue_size(exporter_b._storage) == 0
    assert captured["authorization"] == "Bearer fresh-token"
    exporter_b.shutdown()


def test_restart_replays_using_current_exporter_endpoint_settings(tmp_path):
    storage_dir = tmp_path / "queue"

    exporter_a = _Agent365Exporter(
        token_resolver=lambda a, t: "stale-token",
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    exporter_a._domain_override = "https://stale.example.test"
    exporter_a._post_once = MagicMock(  # type: ignore[method-assign]
        return_value=DeliveryResult(DeliveryDisposition.RETRYABLE, 30)
    )

    assert exporter_a.export([_make_span()]) is SpanExportResult.SUCCESS
    assert _queue_size(exporter_a._storage) == 1
    exporter_a.shutdown()

    captured = {}
    exporter_b = _Agent365Exporter(
        token_resolver=lambda a, t: "fresh-token",
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    exporter_b._domain_override = "https://current.example.test"
    exporter_b._ensure_durable_initialized()

    def fake_post_once(url, body, headers):
        del body, headers
        captured["url"] = url
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    exporter_b._post_once = fake_post_once  # type: ignore[method-assign]

    exporter_b._replay.run_once()

    assert _queue_size(exporter_b._storage) == 0
    assert captured["url"] == (
        "https://current.example.test/observability/tenants/t1/otlp/agents/a1/traces" "?api-version=1"
    )
    exporter_b.shutdown()


def test_restart_replays_record_persisted_after_token_failure(tmp_path):
    storage_dir = tmp_path / "queue"

    # --- Instance A: token resolution fails, so the payload is persisted. ---
    exporter_a = _Agent365Exporter(
        token_resolver=MagicMock(side_effect=RuntimeError("credential outage")),
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    # No send should happen when the token cannot be resolved.
    exporter_a._post_once = MagicMock()  # type: ignore[method-assign]

    assert exporter_a.export([_make_span()]) is SpanExportResult.SUCCESS
    exporter_a._post_once.assert_not_called()
    assert _queue_size(exporter_a._storage) == 1
    exporter_a.shutdown()

    # --- Instance B: credentials recovered; replay drains the queue. ---
    exporter_b = _Agent365Exporter(
        token_resolver=lambda a, t: "recovered-token",
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    exporter_b._ensure_durable_initialized()
    exporter_b._post_once = MagicMock(  # type: ignore[method-assign]
        return_value=DeliveryResult(DeliveryDisposition.DELIVERED)
    )

    exporter_b._replay.run_once()

    assert _queue_size(exporter_b._storage) == 0
    exporter_b._post_once.assert_called_once()
    exporter_b.shutdown()


def test_shutdown_blocks_until_active_replay_send_completes_then_removes_record(tmp_path):
    """Regression for exporter/replay shutdown ownership: exporter.shutdown()
    must not close storage/session while a replay send is in flight. If it
    did, the delete() that follows the DELIVERED result below would silently
    fail against a closed connection, leaving the record duplicated/orphaned
    for the next restart instead of cleanly removed.
    """
    storage_dir = tmp_path / "queue"

    exporter_a = _Agent365Exporter(
        token_resolver=lambda a, t: "token",
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    exporter_a._ensure_durable_initialized()
    identity = IdentityKey(tenant_id="t1", agent_id="a1", agentic_user_id=None, use_s2s_endpoint=False)
    assert exporter_a._storage.store(DurableRecord.new(identity, '{"resourceSpans":[]}'))
    assert _queue_size(exporter_a._storage) == 1

    release_send = threading.Event()
    entered_send = threading.Event()

    def blocking_send(record):
        del record
        entered_send.set()
        release_send.wait()
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    # Patch the coordinator's own _send (read fresh per run_once() call, not
    # yet captured by the not-yet-started thread) before starting it, so the
    # very first pass -- with a fresh, never-throttled gate -- blocks here.
    exporter_a._replay._send = blocking_send
    exporter_a._replay.start()
    assert entered_send.wait(5.0), "replay never reached the blocking send"

    shutdown_thread = threading.Thread(target=exporter_a.shutdown)
    shutdown_thread.start()
    try:
        time.sleep(0.2)
        assert shutdown_thread.is_alive(), "shutdown() must wait for the active replay send"
    finally:
        release_send.set()
        shutdown_thread.join(5.0)
    assert not shutdown_thread.is_alive()

    # Restart against the same directory: the record must be delivered and
    # removed, not stuck leased or resurrected by a corrupted queue.
    exporter_b = _Agent365Exporter(
        token_resolver=lambda a, t: "fresh-token",
        storage_directory=storage_dir,
        enable_durable_delivery=True,
    )
    exporter_b._ensure_durable_initialized()
    assert _queue_size(exporter_b._storage) == 0
    exporter_b.shutdown()
