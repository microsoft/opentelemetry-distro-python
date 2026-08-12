# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the durable replay coordinator."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    IdentityKey,
    TransmissionGate,
)
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import DurableRecord
from microsoft.opentelemetry.a365.core.exporters.replay_coordinator import ReplayCoordinator


IDENTITY = IdentityKey(
    tenant_id="tenant-1",
    agent_id="agent-1",
    agentic_user_id=None,
    use_s2s_endpoint=False,
)

RECORD = DurableRecord(
    schema_version=1,
    tenant_id=IDENTITY.tenant_id,
    agent_id=IDENTITY.agent_id,
    agentic_user_id=IDENTITY.agentic_user_id,
    use_s2s_endpoint=IDENTITY.use_s2s_endpoint,
    url="https://example.test",
    payload='{"value":1}',
    created_at=1.0,
    record_id=1,
)

SECOND_RECORD = DurableRecord(
    schema_version=1,
    tenant_id=IDENTITY.tenant_id,
    agent_id=IDENTITY.agent_id,
    agentic_user_id=IDENTITY.agentic_user_id,
    use_s2s_endpoint=IDENTITY.use_s2s_endpoint,
    url="https://example.test",
    payload='{"value":2}',
    created_at=2.0,
    record_id=2,
)


class FakeStorage:
    """Minimal storage double used to observe replay behavior."""

    def __init__(self, batches: list[list[DurableRecord]]) -> None:
        self._batches = [list(batch) for batch in batches]
        self._lock = threading.Lock()
        self.block_event: threading.Event | None = None
        self.claim_calls = 0
        self.claim_limits: list[int] = []
        self.deleted: list[int] = []
        self.released: list[int] = []

    def claim(self, limit: int, lease_seconds: float) -> list[DurableRecord]:
        del lease_seconds
        with self._lock:
            self.claim_calls += 1
            self.claim_limits.append(limit)
        if self.block_event is not None:
            self.block_event.wait()
        with self._lock:
            if self._batches:
                return self._batches.pop(0)
            return []

    def delete(self, record_id: int) -> bool:
        with self._lock:
            self.deleted.append(record_id)
        return True

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


def test_replay_releases_record_when_send_raises_and_continues() -> None:
    storage = FakeStorage([[RECORD, SECOND_RECORD]])
    gate = MagicMock(spec=TransmissionGate)
    gate.try_acquire.return_value = True

    def send(record: DurableRecord) -> DeliveryResult:
        if record.record_id == RECORD.record_id:
            raise RuntimeError("token resolution failed")
        return DeliveryResult(DeliveryDisposition.DELIVERED)

    coordinator = ReplayCoordinator(storage, gate, send=send)

    coordinator.run_once()

    assert storage.released == [RECORD.record_id]
    assert storage.deleted == [SECOND_RECORD.record_id]
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
