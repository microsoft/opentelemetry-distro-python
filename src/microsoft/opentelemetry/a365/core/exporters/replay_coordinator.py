# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Background replay coordinator for durable telemetry delivery."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    IdentityKey,
    TransmissionGate,
)
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import (
    DurableRecord,
    PersistentStorage,
)

_logger = logging.getLogger(__name__)

_MAX_RECORDS_PER_PASS = 10
_LEASE_SECONDS = 30.0


class ReplayCoordinator:
    """Drive durable record replay on a single daemon thread."""

    def __init__(
        self,
        storage: PersistentStorage,
        gate: TransmissionGate,
        send: Callable[[DurableRecord], DeliveryResult],
    ) -> None:
        self._storage = storage
        self._gate = gate
        self._send = send
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the replay loop on one daemon thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._wake_event.set()
                return
            if self._stop_event.is_set():
                return

            self._wake_event.set()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="ReplayCoordinator",
                daemon=True,
            )
            self._thread.start()

    def wake(self) -> None:
        """Wake the replay thread to run another pass."""
        self._wake_event.set()

    def shutdown(self, timeout_seconds: float) -> bool:
        """Stop the replay thread and wait up to *timeout_seconds* for it."""
        with self._lock:
            thread = self._thread
            self._stop_event.set()
            self._wake_event.set()
        if thread is None:
            return True
        thread.join(timeout_seconds)
        return not thread.is_alive()

    def run_once(self) -> None:
        """Claim and process a single bounded replay batch."""
        records = self._storage.claim(_MAX_RECORDS_PER_PASS, _LEASE_SECONDS)
        if not records:
            return

        for index, record in enumerate(records):
            if self._stop_event.is_set():
                self._release_remaining(records, index)
                return

            identity = self._identity_for(record)
            if not self._gate.try_acquire(identity):
                self._release_record(record)
                continue

            try:
                result = self._send(record)
            except Exception as exc:  # pylint: disable=broad-except
                _logger.debug("Replay send failed for record %s: %s", record.record_id, exc)
                self._release_record(record)
                self._gate.release_probe(identity)
                continue

            if result.disposition is DeliveryDisposition.DELIVERED:
                self._delete_record(record)
                self._gate.record_success(identity)
                continue

            if result.disposition is DeliveryDisposition.PERMANENT:
                self._delete_record(record)
                self._gate.record_success(identity)
                continue

            self._gate.record_retryable_failure(identity, result.retry_after)
            self._release_record(record)
            self._release_remaining(records, index + 1)
            return

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.wait()
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self.run_once()

    @staticmethod
    def _identity_for(record: DurableRecord) -> IdentityKey:
        return IdentityKey(
            tenant_id=record.tenant_id,
            agent_id=record.agent_id,
            agentic_user_id=record.agentic_user_id,
            use_s2s_endpoint=record.use_s2s_endpoint,
        )

    def _delete_record(self, record: DurableRecord) -> None:
        if record.record_id is not None:
            self._storage.delete(record.record_id)

    def _release_record(self, record: DurableRecord) -> None:
        if record.record_id is not None:
            self._storage.release(record.record_id)

    def _release_remaining(self, records: list[DurableRecord], start_index: int) -> None:
        for record in records[start_index:]:
            self._release_record(record)


__all__ = ["ReplayCoordinator"]
