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

# Background cadence: even without an explicit wake(), the replay loop re-runs a
# pass on this interval so a startup backlog larger than one pass (or records
# left behind by a bounded pass) is eventually drained. Matches the durable
# design's "wakes on new persisted work and periodically" contract.
_REPLAY_POLL_INTERVAL_SECONDS = 30.0


class ReplayIdentityError(Exception):
    """Raised by the send callback when an identity or token cannot be resolved.

    When the coordinator catches this exception, it releases the current record
    and releases the gate probe for that identity, then continues processing
    remaining records in the batch.  This is appropriate for transient,
    per-identity failures (e.g. credential look-up errors) that should not
    block delivery of records belonging to other identities.

    Contrast with unexpected / general exceptions, which cause the coordinator
    to release *all* remaining leased records and abort the current pass.
    """


class ReplayEndpointError(Exception):
    """Raised when replay cannot safely use the current exporter endpoint.

    Task 2 raises this from the replay send callback when the reconstructed
    endpoint is invalid for bearer-token replay (for example, non-HTTPS). Task
    3 will add coordinator-specific handling.
    """


class ReplayCoordinator:
    """Drive durable record replay on a single daemon thread."""

    def __init__(
        self,
        storage: PersistentStorage,
        gate: TransmissionGate,
        send: Callable[[DurableRecord], DeliveryResult],
        poll_interval_seconds: float = _REPLAY_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._storage = storage
        self._gate = gate
        self._send = send
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the replay loop on one daemon thread.

        Calling ``start()`` after ``shutdown()`` is a deliberate safe no-op:
        once the stop event has been set the coordinator is permanently
        stopped and a new instance should be created instead.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._wake_event.set()
                return
            if self._stop_event.is_set():
                _logger.debug("ReplayCoordinator: start() called after shutdown — ignored")
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

    def run_once(self) -> bool:
        """Claim and process a single bounded replay batch.

        Returns ``True`` only when a maximal batch (``_MAX_RECORDS_PER_PASS``)
        was claimed *and* every record in it reached a terminal state
        (delivered or permanently dropped). In that case more records may
        remain and the loop should run again immediately. It returns ``False``
        for an empty/partial batch, when the pass was stopped early (retryable
        failure, shutdown, or unexpected error), or when any record was left
        behind (gate-blocked or released), so the loop falls back to the
        periodic cadence and does not busy-spin.
        """
        records = self._storage.claim(_MAX_RECORDS_PER_PASS, _LEASE_SECONDS)
        if not records:
            return False

        deleted_count = 0
        for index, record in enumerate(records):
            if self._stop_event.is_set():
                self._release_remaining(records, index)
                return False

            identity = self._identity_for(record)
            if not self._gate.try_acquire(identity):
                self._release_record(record)
                continue

            try:
                result = self._send(record)
            except ReplayIdentityError as exc:
                # Per-identity token/credential failure: release this record and
                # its gate probe, but continue processing the rest of the batch.
                _logger.debug(
                    "Replay identity error for record %s: %s", record.record_id, exc
                )
                self._release_record(record)
                self._gate.release_probe(identity)
                continue
            except ReplayEndpointError as exc:
                _logger.warning(
                    "Replay endpoint error for record %s: %s",
                    record.record_id,
                    exc,
                )
                self._release_record(record)
                self._gate.release_probe(identity)
                self._release_remaining(records, index + 1)
                return False
            except Exception as exc:  # pylint: disable=broad-except
                # Unexpected failure: release the current record and all
                # remaining leased records, then abort the pass so we do not
                # send stale data after an unknown error.
                _logger.warning(
                    "Unexpected error during replay for record %s: %s",
                    record.record_id,
                    exc,
                    exc_info=True,
                )
                self._release_record(record)
                self._gate.release_probe(identity)
                self._release_remaining(records, index + 1)
                return False

            if result.disposition is DeliveryDisposition.DELIVERED:
                deleted = self._delete_record(record, reason="delivered")
                self._gate.record_success(identity)
                if deleted:
                    deleted_count += 1
                continue

            if result.disposition is DeliveryDisposition.PERMANENT:
                # Permanent failures (e.g. 400 Bad Request) indicate the
                # payload is undeliverable regardless of retry count.  We
                # delete the record to avoid re-queuing it forever and call
                # record_success so the gate resets: the identity itself is
                # healthy; only this particular record was rejected.
                deleted = self._delete_record(record, reason="permanent")
                self._gate.record_success(identity)
                if deleted:
                    deleted_count += 1
                continue

            self._gate.record_retryable_failure(identity, result.retry_after)
            self._release_record(record)
            self._release_remaining(records, index + 1)
            return False

        # Only request an immediate re-run when we fully drained a maximal
        # batch; otherwise re-claiming would return records that are still
        # gated/leased and spin the loop.
        return (
            deleted_count == len(records)
            and len(records) >= _MAX_RECORDS_PER_PASS
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            # A set wake event returns immediately; otherwise wake on the fixed
            # background cadence so leftover records are not stranded until an
            # external wake() arrives.
            self._wake_event.wait(self._poll_interval_seconds)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            # Drain consecutive full passes so a startup backlog larger than one
            # pass is not left at >10 records until the next wake.
            try:
                while not self._stop_event.is_set() and self.run_once():
                    pass
            except Exception:  # pylint: disable=broad-except
                # An unexpected exception from run_once (e.g. a programming bug,
                # unexpected storage error not caught inside run_once) must not
                # permanently kill the thread.  Log it and fall back to the
                # periodic cadence so later passes have a chance to succeed.
                _logger.exception(
                    "ReplayCoordinator: unexpected exception from run_once; "
                    "replay thread will retry on the next periodic wake"
                )

    @staticmethod
    def _identity_for(record: DurableRecord) -> IdentityKey:
        return IdentityKey(
            tenant_id=record.tenant_id,
            agent_id=record.agent_id,
            agentic_user_id=record.agentic_user_id,
            use_s2s_endpoint=record.use_s2s_endpoint,
        )

    def _delete_record(self, record: DurableRecord, reason: str) -> bool:
        if record.record_id is None:
            return False

        deleted = self._storage.delete(record.record_id)
        if deleted:
            return True

        if reason == "delivered":
            _logger.warning(
                "Replay delete failed for delivered record %s; duplicate delivery may occur.",
                record.record_id,
            )
        else:
            _logger.warning(
                "Replay delete failed for permanent record %s; poison record may recur.",
                record.record_id,
            )
        return False

    def _release_record(self, record: DurableRecord) -> None:
        if record.record_id is not None:
            self._storage.release(record.record_id)

    def _release_remaining(self, records: list[DurableRecord], start_index: int) -> None:
        for record in records[start_index:]:
            self._release_record(record)


__all__ = ["ReplayCoordinator", "ReplayEndpointError", "ReplayIdentityError"]
