# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the durable replay coordinator."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from microsoft.opentelemetry.a365.constants import A365_HTTP_TIMEOUT_SECONDS
from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    IdentityKey,
    TransmissionGate,
)
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import DurableRecord
from microsoft.opentelemetry.a365.core.exporters.replay_coordinator import (
    _LEASE_SECONDS,
    _MAX_RECORDS_PER_PASS,
    ReplayCoordinator,
    ReplayEndpointError,
    ReplayIdentityError,
)

IDENTITY = IdentityKey(
    tenant_id="tenant-1",
    agent_id="agent-1",
    agentic_user_id=None,
    use_s2s_endpoint=False,
)


def _record_kwargs(record_id: int, payload: str, created_at: float) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "schema_version": 1 if "url" in DurableRecord.__dataclass_fields__ else 2,
        "tenant_id": IDENTITY.tenant_id,
        "agent_id": IDENTITY.agent_id,
        "agentic_user_id": IDENTITY.agentic_user_id,
        "use_s2s_endpoint": IDENTITY.use_s2s_endpoint,
        "payload": payload,
        "created_at": created_at,
        "record_id": record_id,
    }
    if "url" in DurableRecord.__dataclass_fields__:
        kwargs["url"] = "https://example.test"
    return kwargs


RECORD = DurableRecord(**_record_kwargs(1, '{"value":1}', 1.0))

SECOND_RECORD = DurableRecord(**_record_kwargs(2, '{"value":2}', 2.0))


def _make_record(record_id: int) -> DurableRecord:
    """Build a distinct durable record for backlog tests."""
    return DurableRecord(**_record_kwargs(record_id, f'{{"value":{record_id}}}', float(record_id)))


class FakeStorage:
    """Minimal storage double used to observe replay behavior."""

    def __init__(
        self,
        batches: list[list[DurableRecord]],
        *,
        delete_result: bool = True,
        delete_results: dict[int, bool] | None = None,
    ) -> None:
        self._batches = [list(batch) for batch in batches]
        self._delete_result = delete_result
        self._delete_results = delete_results or {}
        self._lock = threading.Lock()
        self.block_event: threading.Event | None = None
        self.claim_calls = 0
        self.claim_limits: list[int] = []
        self.claim_lease_seconds: list[float] = []
        self.deleted: list[int] = []
        self.released: list[int] = []

    def claim(self, limit: int, lease_seconds: float) -> list[DurableRecord]:
        with self._lock:
            self.claim_calls += 1
            self.claim_limits.append(limit)
            self.claim_lease_seconds.append(lease_seconds)
        if self.block_event is not None:
            self.block_event.wait()
        with self._lock:
            if self._batches:
                return self._batches.pop(0)
            return []

    def delete(self, record_id: int) -> bool:
        with self._lock:
            self.deleted.append(record_id)
        return self._delete_results.get(record_id, self._delete_result)

    def release(self, record_id: int) -> bool:
        with self._lock:
            self.released.append(record_id)
        return True


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_replay_deletes_delivered_record() -> None:
    storage = FakeStorage([[RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.run_once()

    assert storage.deleted == [RECORD.record_id]
    assert storage.released == []
    gate.record_success.assert_called_once_with(IDENTITY)


def test_replay_lease_covers_worst_case_full_pass() -> None:
    storage = FakeStorage([[RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.run_once()

    assert storage.claim_limits == [_MAX_RECORDS_PER_PASS]
    assert storage.claim_lease_seconds == [_LEASE_SECONDS]
    assert _LEASE_SECONDS > _MAX_RECORDS_PER_PASS * A365_HTTP_TIMEOUT_SECONDS


def test_replay_retains_retryable_record_and_updates_gate() -> None:
    storage = FakeStorage([[RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.RETRYABLE, retry_after=45),
    )

    coordinator.run_once()

    assert storage.released == [RECORD.record_id]
    assert storage.deleted == []
    gate.record_retryable_failure.assert_called_once_with(IDENTITY, 45)


def test_replay_deletes_permanent_record() -> None:
    storage = FakeStorage([[RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.PERMANENT),
    )

    coordinator.run_once()

    assert storage.deleted == [RECORD.record_id]
    assert storage.released == []
    gate.record_success.assert_called_once_with(IDENTITY)


def test_delete_failure_after_success_logs_duplicate_risk(caplog) -> None:
    storage = FakeStorage([[RECORD]], delete_result=False)
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.run_once()

    assert "duplicate delivery" in caplog.text.lower()
    gate.record_success.assert_called_once_with(IDENTITY)


def test_full_batch_delete_failure_after_delivered_records_returns_false() -> None:
    full_batch = [_make_record(i) for i in range(1, 11)]
    failed_record_id = full_batch[-1].record_id
    assert failed_record_id is not None
    storage = FakeStorage([full_batch], delete_results={failed_record_id: False})
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    assert coordinator.run_once() is False
    assert len(storage.deleted) == 10


def test_delete_failure_after_permanent_logs_poison_record_risk(caplog) -> None:
    storage = FakeStorage([[RECORD]], delete_result=False)
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.PERMANENT),
    )

    coordinator.run_once()

    assert "poison record may recur" in caplog.text.lower()
    gate.record_success.assert_called_once_with(IDENTITY)


def test_full_batch_delete_failure_after_permanent_records_returns_false() -> None:
    full_batch = [_make_record(i) for i in range(1, 11)]
    failed_record_id = full_batch[0].record_id
    assert failed_record_id is not None
    storage = FakeStorage([full_batch], delete_results={failed_record_id: False})
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.PERMANENT),
    )

    assert coordinator.run_once() is False
    assert len(storage.deleted) == 10


def test_endpoint_error_retains_record_and_stops_pass(caplog) -> None:
    storage = FakeStorage([[RECORD, SECOND_RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True

    def send(record: DurableRecord) -> DeliveryResult:
        if record.record_id == RECORD.record_id:
            raise ReplayEndpointError("invalid replay endpoint")
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    coordinator = ReplayCoordinator(storage, gate, send=send)

    assert coordinator.run_once() is False
    assert storage.deleted == []
    assert storage.released == [RECORD.record_id, SECOND_RECORD.record_id]
    assert "unexpected error during replay" not in caplog.text.lower()
    gate.release_probe.assert_called_once_with(IDENTITY)


def test_replay_releases_record_when_identity_error_and_continues() -> None:
    """ReplayIdentityError: release current record and continue the batch."""
    storage = FakeStorage([[RECORD, SECOND_RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True

    def send(record: DurableRecord) -> DeliveryResult:
        if record.record_id == RECORD.record_id:
            raise ReplayIdentityError("token resolution failed")
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    coordinator = ReplayCoordinator(storage, gate, send=send)

    coordinator.run_once()

    assert storage.released == [RECORD.record_id]
    assert storage.deleted == [SECOND_RECORD.record_id]
    gate.release_probe.assert_called_once_with(IDENTITY)


def test_general_exception_releases_current_and_remaining_and_stops() -> None:
    """Unexpected exceptions: release current + remaining records and stop the pass."""
    storage = FakeStorage([[RECORD, SECOND_RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True

    def send(record: DurableRecord) -> DeliveryResult:
        if record.record_id == RECORD.record_id:
            raise RuntimeError("unexpected crash")
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    coordinator = ReplayCoordinator(storage, gate, send=send)

    coordinator.run_once()

    assert RECORD.record_id in storage.released
    assert SECOND_RECORD.record_id in storage.released
    assert storage.deleted == []
    gate.release_probe.assert_called_once_with(IDENTITY)


def test_run_once_claims_at_most_ten_records() -> None:
    storage = FakeStorage([[RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(storage, gate, send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED))

    coordinator.run_once()

    assert storage.claim_limits == [10]


def test_start_and_wake_process_a_later_batch() -> None:
    storage = FakeStorage([[], [RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.start()
    try:
        assert wait_until(lambda: storage.claim_calls >= 1)
        assert storage.deleted == []

        coordinator.wake()

        assert wait_until(lambda: storage.deleted == [RECORD.record_id])
    finally:
        coordinator.shutdown(1.0)


def test_shutdown_is_bounded_and_idempotent() -> None:
    storage = FakeStorage([[RECORD]])
    storage.block_event = threading.Event()
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.start()
    try:
        assert wait_until(lambda: storage.claim_calls >= 1)

        started = time.monotonic()
        assert coordinator.shutdown(0.05) is False
        assert time.monotonic() - started < 0.5

        storage.block_event.set()
        assert wait_until(lambda: coordinator.shutdown(1.0))
        assert coordinator.shutdown(0.05) is True
    finally:
        storage.block_event.set()
        coordinator.shutdown(1.0)


def test_shutdown_default_timeout_waits_unbounded_for_active_work() -> None:
    """shutdown() with no argument (the new default) must block until the
    thread actually exits, not return early while replay work is active."""
    storage = FakeStorage([[RECORD]])
    storage.block_event = threading.Event()
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.start()
    try:
        assert wait_until(lambda: storage.claim_calls >= 1)

        result: dict[str, bool] = {}

        def call_default_shutdown() -> None:
            result["stopped"] = coordinator.shutdown()

        shutdown_thread = threading.Thread(target=call_default_shutdown)
        shutdown_thread.start()

        # The replay thread is still blocked inside claim(); the unbounded
        # shutdown() call must still be waiting, not have returned already.
        time.sleep(0.2)
        assert shutdown_thread.is_alive()

        storage.block_event.set()
        shutdown_thread.join(2.0)
        assert not shutdown_thread.is_alive()
        assert result["stopped"] is True
    finally:
        storage.block_event.set()
        coordinator.shutdown(1.0)


def test_gate_blocked_releases_record_without_send() -> None:
    """When the gate blocks an identity, the record is released without calling send."""
    storage = FakeStorage([[RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = False
    send = MagicMock()
    coordinator = ReplayCoordinator(storage, gate, send=send)

    coordinator.run_once()

    assert storage.released == [RECORD.record_id]
    assert storage.deleted == []
    send.assert_not_called()


def test_start_after_shutdown_is_safe_noop() -> None:
    """Calling start() after shutdown() is a safe no-op: no new thread is spawned."""
    storage = FakeStorage([[]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.start()
    coordinator.shutdown(1.0)
    thread_before = coordinator._thread

    # start() after shutdown must not raise and must not spawn a new thread
    coordinator.start()

    assert coordinator._thread is thread_before


def test_mid_batch_stop_releases_remaining_records() -> None:
    """When stop_event fires mid-batch, all un-processed records are released."""
    storage = FakeStorage([[RECORD, SECOND_RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    # Simulate stop being set before the first record is processed
    coordinator._stop_event.set()

    coordinator.run_once()

    assert RECORD.record_id in storage.released
    assert SECOND_RECORD.record_id in storage.released
    assert storage.deleted == []


def test_run_once_requests_continuation_after_full_pass() -> None:
    """A fully-drained maximal batch signals that more records may remain."""
    full_batch = [_make_record(i) for i in range(1, 11)]  # exactly 10
    storage = FakeStorage([full_batch])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    assert coordinator.run_once() is True
    assert len(storage.deleted) == 10


def test_run_once_does_not_request_continuation_for_partial_pass() -> None:
    """A batch smaller than the pass cap does not request an immediate re-run."""
    storage = FakeStorage([[RECORD, SECOND_RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    assert coordinator.run_once() is False


def test_run_once_no_continuation_when_full_pass_gate_blocked() -> None:
    """A full batch that is entirely gate-blocked must NOT request continuation,
    otherwise the loop would busy-spin re-claiming the same records."""
    full_batch = [_make_record(i) for i in range(1, 11)]
    storage = FakeStorage([full_batch])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = False  # every record is gate-blocked
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    assert coordinator.run_once() is False
    assert len(storage.released) == 10
    assert storage.deleted == []


def test_start_drains_backlog_larger_than_one_pass() -> None:
    """A startup backlog larger than one pass is fully drained after a wake,
    not left at >10 records until the next external wake."""
    first = [_make_record(i) for i in range(1, 11)]  # 10 records
    second = [_make_record(i) for i in range(11, 16)]  # 5 records
    storage = FakeStorage([first, second])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
    )

    coordinator.start()
    try:
        assert wait_until(lambda: len(storage.deleted) == 15)
    finally:
        coordinator.shutdown(1.0)


def test_periodic_wake_processes_backlog_without_external_wake() -> None:
    """A fixed periodic wake re-runs a pass even without an explicit wake(),
    so records left behind are eventually drained on the background cadence."""
    # First pass claims nothing; a record only becomes available on the second
    # pass, which must be triggered by the periodic timeout (no wake() call).
    storage = FakeStorage([[], [RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
        poll_interval_seconds=0.05,
    )

    coordinator.start()
    try:
        # No coordinator.wake() here: only the periodic timeout can drive the
        # second pass that deletes the record.
        assert wait_until(lambda: storage.deleted == [RECORD.record_id])
    finally:
        coordinator.shutdown(1.0)


# ---------------------------------------------------------------------------
# Regression test: unexpected exception from run_once must not kill the thread
# ---------------------------------------------------------------------------


def test_run_loop_survives_unexpected_exception_from_run_once() -> None:
    """An unexpected exception raised inside _run_loop (outside run_once's own
    broad-except) must be caught and logged so the replay thread stays alive.

    The test monkey-patches the coordinator instance's run_once to throw a
    RuntimeError on the first call, then verifies the thread still delivers a
    record on the next periodic wake.
    """
    calls: list[int] = []
    storage = FakeStorage([[], [RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True

    original_run_once = ReplayCoordinator.run_once

    def patched_run_once(self: ReplayCoordinator) -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("injected fault in run_once")
        return original_run_once(self)

    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(DeliveryDisposition.DELIVERED),
        poll_interval_seconds=0.05,
    )
    coordinator.run_once = patched_run_once.__get__(coordinator, ReplayCoordinator)  # type: ignore[method-assign]

    coordinator.start()
    try:
        # The thread must survive the injected fault and process the second pass.
        assert wait_until(
            lambda: storage.deleted == [RECORD.record_id], timeout=3.0
        ), "replay thread did not recover after unexpected exception from run_once"
    finally:
        coordinator.shutdown(1.0)
