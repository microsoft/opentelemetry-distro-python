# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Agent365 record adapter for Azure Monitor's offline storage provider."""

from __future__ import annotations

import json
import logging
import math
import os
import stat
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import TracebackType

from azure.monitor.opentelemetry.exporter._storage import LocalFileBlob, LocalFileStorage, StorageExportResult
from azure.monitor.opentelemetry.exporter.export._base import _get_storage_directory

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import IdentityKey

_logger = logging.getLogger(__name__)
_DEFAULT_CAPACITY_BYTES = 50 * 1024 * 1024
_DEFAULT_RETENTION_SECONDS = 2 * 24 * 3600
_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class DurableRecord:
    """An identity and telemetry payload, never a replay URL or bearer token."""

    schema_version: int
    tenant_id: str
    agent_id: str
    agentic_user_id: str | None
    use_s2s_endpoint: bool
    payload: str
    created_at: float
    lease_until: float | None = None
    retry_count: int = 0
    record_id: int | None = field(default=None)

    @staticmethod
    def new(key: IdentityKey, payload: str) -> DurableRecord:
        """Construct an unpersisted record from an IdentityKey."""
        return DurableRecord(
            schema_version=_SCHEMA_VERSION,
            tenant_id=key.tenant_id,
            agent_id=key.agent_id,
            agentic_user_id=key.agentic_user_id,
            use_s2s_endpoint=key.use_s2s_endpoint,
            payload=payload,
            created_at=time.time(),
        )


class PersistentStorage:
    """Adapt Agent365 replay to Azure Monitor's files, leases and permissions.

    Each blob holds one identity envelope. Configured roots get an ``a365``
    child. Use separate sibling roots for Azure Monitor and Agent365;
    shared or overlapping cache paths are unsupported and are not rejected.
    """

    def __init__(
        self,
        directory: str | Path | None = None,
        capacity_bytes: int = _DEFAULT_CAPACITY_BYTES,
        retention_seconds: float = _DEFAULT_RETENTION_SECONDS,
    ) -> None:
        if directory is not None and (not isinstance(directory, (str, Path)) or not str(directory).strip()):
            raise ValueError("storage_directory must be a non-empty string path, Path, or None")
        if directory is None:
            self.directory = Path(_get_storage_directory("agent365"))
        else:
            root = Path(directory).absolute()
            if sys.platform != "win32":
                try:
                    root_stat = root.lstat()
                except FileNotFoundError:
                    root.mkdir(mode=0o700, parents=True, exist_ok=True)
                    root_stat = root.lstat()
                if not stat.S_ISDIR(root_stat.st_mode):
                    raise PermissionError(f"Agent365 storage root must be a directory, not a file or symlink: {root}")
                if root_stat.st_uid not in (os.getuid(), 0):  # pylint: disable=no-member
                    raise PermissionError(f"Agent365 storage root must be owned by the current user or root: {root}")
                if root_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                    raise PermissionError(f"Agent365 storage root must not be group- or world-writable: {root}")
            self.directory = root / "a365"
        self._capacity_bytes = capacity_bytes
        self._retention_seconds = retention_seconds
        self._lock = threading.RLock()
        self._closed = False
        self._next_record_id = 0
        self._claimed: dict[int, tuple[LocalFileBlob, float]] = {}
        if directory is not None and (Path(directory) / "queue.db").exists():
            _logger.warning(
                "Legacy Agent365 SQLite backlog exists at %s; it is not migrated or replayed by "
                "Azure Monitor file storage. Drain it with the previous SDK before upgrading.",
                Path(directory) / "queue.db",
            )
        self._provider = LocalFileStorage(
            str(self.directory),
            max_size=capacity_bytes,
            retention_period=math.ceil(retention_seconds),
            name="Agent365Storage",
        )
        # The provider reports permission failures by disabling itself, rather
        # than raising. Propagate that state to the exporter's nonfatal handler.
        if not self._provider._enabled:  # pylint: disable=protected-access
            self._provider.close()
            raise OSError("Azure Monitor local file storage could not be initialized")

    def store(self, record: DurableRecord) -> bool:
        """Persist one envelope using the upstream atomic blob writer."""
        with self._lock:
            if self._closed:
                _logger.error("PersistentStorage.store failed: storage is closed")
                return False
            envelope = asdict(record)
            del envelope["record_id"]
            del envelope["lease_until"]
            if len(json.dumps(envelope).encode("utf-8")) > self._capacity_bytes:
                _logger.error("PersistentStorage.store failed: record exceeds storage capacity")
                return False
            result = self._provider.put([envelope], lease_period=0)
            if result != StorageExportResult.LOCAL_FILE_BLOB_SUCCESS:
                _logger.error("PersistentStorage.store failed: %s", result)
                return False
            return True

    def claim(self, limit: int, lease_seconds: float) -> list[DurableRecord]:
        """Lease blobs atomically using the upstream rename-based lease."""
        with self._lock:
            if self._closed:
                _logger.error("PersistentStorage.claim failed: storage is closed")
                return []
            now = time.time()
            self._claimed = {key: entry for key, entry in self._claimed.items() if entry[1] > now}
            records: list[DurableRecord] = []
            for blob in self._provider.gets():
                if len(records) >= limit:
                    break
                leased = blob.lease(math.ceil(lease_seconds))
                if leased is None:
                    continue
                data = leased.get()
                # Upstream returns None for both corrupt JSON and transient I/O
                # failures. Do not discard a potentially valid unreadable blob.
                if data is None:
                    _logger.error(
                        "PersistentStorage.claim failed to read durable record; retained: %s", leased.fullpath
                    )
                    if leased.lease(0) is None:
                        _logger.error("PersistentStorage.release failed for unreadable blob: %s", leased.fullpath)
                    continue
                try:
                    if len(data) != 1 or not isinstance(data[0], dict):
                        raise ValueError("expected one Agent365 identity envelope")
                    record = self._decode_record(data[0])
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    _logger.warning("PersistentStorage.claim dropped invalid durable record: %s", exc)
                    self._delete_blob(leased)
                    continue
                if record.created_at < now - self._retention_seconds:
                    self._delete_blob(leased)
                    continue
                self._next_record_id += 1
                record_id = self._next_record_id
                lease_until = now + math.ceil(lease_seconds)
                self._claimed[record_id] = (leased, lease_until)
                records.append(
                    DurableRecord(
                        schema_version=record.schema_version,
                        tenant_id=record.tenant_id,
                        agent_id=record.agent_id,
                        agentic_user_id=record.agentic_user_id,
                        use_s2s_endpoint=record.use_s2s_endpoint,
                        payload=record.payload,
                        created_at=record.created_at,
                        retry_count=record.retry_count,
                        lease_until=lease_until,
                        record_id=record_id,
                    )
                )
            return records

    @staticmethod
    def _decode_record(data: dict) -> DurableRecord:
        for name in ("tenant_id", "agent_id", "payload"):
            if not isinstance(data.get(name), str) or not data[name].strip():
                raise ValueError(f"blank or invalid {name}")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        if not isinstance(data.get("use_s2s_endpoint"), bool):
            raise ValueError("invalid use_s2s_endpoint")
        if data.get("agentic_user_id") is not None and not isinstance(data["agentic_user_id"], str):
            raise ValueError("invalid agentic_user_id")
        created_at = data["created_at"]
        if isinstance(created_at, bool) or not isinstance(created_at, (int, float)) or not math.isfinite(created_at):
            raise ValueError("invalid created_at")
        retry_count = data.get("retry_count", 0)
        if isinstance(retry_count, bool) or not isinstance(retry_count, int) or retry_count < 0:
            raise ValueError("invalid retry_count")
        return DurableRecord(
            schema_version=_SCHEMA_VERSION,
            tenant_id=data["tenant_id"],
            agent_id=data["agent_id"],
            agentic_user_id=data.get("agentic_user_id"),
            use_s2s_endpoint=data["use_s2s_endpoint"],
            payload=data["payload"],
            created_at=created_at,
            retry_count=retry_count,
        )

    @staticmethod
    def _delete_blob(blob: LocalFileBlob) -> bool:
        blob.delete()
        if Path(blob.fullpath).exists():
            _logger.error("PersistentStorage.delete failed: blob was not removed: %s", blob.fullpath)
            return False
        return True

    def delete(self, record_id: int) -> bool:
        """Delete a claimed blob, reporting upstream's otherwise-silent failure."""
        with self._lock:
            entry = self._claimed.get(record_id)
            if entry is None:
                return False
            if not self._delete_blob(entry[0]):
                return False
            del self._claimed[record_id]
            return True

    def release(self, record_id: int) -> bool:
        """Expire a claimed blob's lease so another replay pass can claim it."""
        with self._lock:
            entry = self._claimed.get(record_id)
            if entry is None:
                return False
            if entry[0].lease(0) is None:
                _logger.error("PersistentStorage.release failed: could not release blob %s", entry[0].fullpath)
                return False
            del self._claimed[record_id]
            return True

    def close(self) -> None:
        """Stop the upstream maintenance task."""
        with self._lock:
            if not self._closed:
                self._provider.close()
                self._claimed.clear()
                self._closed = True

    def __enter__(self) -> PersistentStorage:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()


__all__ = ["DurableRecord", "PersistentStorage"]
