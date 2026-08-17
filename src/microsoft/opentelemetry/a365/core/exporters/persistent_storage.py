# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Secure SQLite-backed durable queue for A365 telemetry delivery."""

from __future__ import annotations

import getpass
import hashlib
import logging
import ntpath
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import IdentityKey

_logger = logging.getLogger(__name__)

_DEFAULT_CAPACITY_BYTES = 50 * 1024 * 1024  # 50 MB
_DEFAULT_RETENTION_SECONDS = 2 * 24 * 3600  # 2 days

_SCHEMA_VERSION = 2


def _table_ddl(table_name: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    agentic_user_id TEXT,
    use_s2s_endpoint INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    lease_until REAL,
    retry_count INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class DurableRecord:
    """An envelope for one telemetry payload."""

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


def _resolve_default_directory() -> Path:
    digest = hashlib.sha256((getpass.getuser() + sys.executable + str(Path.cwd())).encode()).hexdigest()[:16]
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        if xdg:
            base = Path(xdg)
        else:
            # Prefer ~/.local/state (created on demand) rather than falling back
            # to a shared temp dir merely because the path does not exist yet.
            # Only fall back when the home directory cannot be resolved at all.
            try:
                base = Path.home() / ".local" / "state"
            except (RuntimeError, OSError):
                base = Path(tempfile.gettempdir())
    return base / "a365-durable-queue" / digest


def _restrict_windows_directory_permissions(directory: Path) -> None:
    """Restrict a Windows queue directory to administrators and the current user."""
    domain = os.environ.get("USERDOMAIN")
    username = os.environ.get("USERNAME")
    current_user = f"{domain}\\{username}" if domain and username else os.getlogin()
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    icacls = ntpath.join(system_root, "System32", "icacls.exe")
    commands = [
        [icacls, str(directory), "/reset", "/T"],
        [
            icacls,
            str(directory),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-32-544:(OI)(CI)F",
            f"{current_user}:(OI)(CI)F",
        ],
    ]
    for command in commands:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0:
            continue
        detail = result.stderr.strip() or f"icacls exited with code {result.returncode}"
        raise PermissionError(f"Could not restrict durable queue permissions: {detail}")


def _ensure_private_directory(directory: Path) -> None:
    """Create the directory with mode 0700, or validate ownership if it exists."""
    if directory.exists():
        if os.name == "nt":
            _restrict_windows_directory_permissions(directory)
            return
        # Use a non-symlink-following lstat so a symlinked queue directory
        # cannot redirect telemetry writes outside a private, caller-owned
        # location or defeat the ownership check via its target.
        st = os.lstat(directory)
        if stat.S_ISLNK(st.st_mode):
            raise PermissionError(f"Durable queue directory must not be a symlink: {directory}")
        if st.st_uid != getattr(os, "getuid")():
            raise PermissionError(f"Durable queue directory has unsafe ownership: {directory}")
        os.chmod(directory, 0o700)
        return
    # Create parents first (no mode enforcement needed for intermediate dirs),
    # then create the final directory with explicit mode so the kernel sets it
    # before any child entry can appear. chmod follows to override a restrictive umask.
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        _restrict_windows_directory_permissions(directory)
        return
    os.chmod(directory, 0o700)


class PersistentStorage:
    """Thread-safe SQLite-backed durable record queue."""

    def __init__(
        self,
        directory: Path | None = None,
        capacity_bytes: int = _DEFAULT_CAPACITY_BYTES,
        retention_seconds: float = _DEFAULT_RETENTION_SECONDS,
    ) -> None:
        self._directory = Path(directory) if directory is not None else _resolve_default_directory()
        self._capacity_bytes = capacity_bytes
        self._retention_seconds = retention_seconds
        self._lock = threading.RLock()

        _ensure_private_directory(self._directory)

        self.database_path = self._directory / "queue.db"
        # isolation_level=None → autocommit; all transactions are explicit.
        self._conn = sqlite3.connect(str(self.database_path), check_same_thread=False, isolation_level=None)
        if os.name != "nt":
            os.chmod(self.database_path, 0o600)

        self._conn.execute("PRAGMA journal_mode=WAL")
        self._initialize_schema()

        if os.name != "nt":
            # WAL journal initialization creates the -wal/-shm sidecars, which can
            # hold the same OTLP payloads as the DB. Lock the DB and any existing
            # sidecars to owner-only now; the 0700 directory keeps future sidecars
            # private on creation.
            self._restrict_file_permissions()

    def _initialize_schema(self) -> None:
        """Create the current schema or migrate the legacy url-backed schema."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            columns = self._table_columns("durable_records")
            if not columns:
                self._conn.execute(_table_ddl("durable_records"))
            elif "url" in columns:
                self._migrate_legacy_schema()
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            self._conn.execute("ROLLBACK")
            raise

    def _table_columns(self, table_name: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row[1] for row in rows}

    def _migrate_legacy_schema(self) -> None:
        """Rewrite the v1 url-backed table into the v2 identity-only schema."""
        self._conn.execute("DROP TABLE IF EXISTS durable_records_v2")
        self._conn.execute(_table_ddl("durable_records_v2"))
        self._conn.execute(
            """
            INSERT INTO durable_records_v2 (
                id, schema_version, tenant_id, agent_id, agentic_user_id,
                use_s2s_endpoint, payload, created_at, lease_until, retry_count
            )
            SELECT
                id,
                ?,
                tenant_id,
                agent_id,
                agentic_user_id,
                use_s2s_endpoint,
                payload,
                created_at,
                lease_until,
                retry_count
            FROM durable_records
            """,
            (_SCHEMA_VERSION,),
        )
        self._conn.execute("DROP TABLE durable_records")
        self._conn.execute("ALTER TABLE durable_records_v2 RENAME TO durable_records")

    def _restrict_file_permissions(self) -> None:
        """Restrict the DB and any existing WAL/SHM sidecars to owner-only (0600).

        Callers gate this on POSIX; on Windows the durable queue relies on the
        private (0700) directory for confidentiality.
        """
        for suffix in ("", "-wal", "-shm"):
            sidecar = Path(f"{self.database_path}{suffix}")
            if sidecar.exists():
                os.chmod(sidecar, 0o600)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, record: DurableRecord) -> bool:
        """Persist a record. Returns False (and logs) if storage fails."""
        with self._lock:
            try:
                now = time.time()
                expire_before = now - self._retention_seconds

                self._conn.execute("BEGIN IMMEDIATE")
                # Prune expired rows first
                self._conn.execute(
                    "DELETE FROM durable_records WHERE created_at < ?",
                    (expire_before,),
                )

                # Capacity check based on live (in-use) pages. SQLite does not
                # shrink the file on delete; freed pages move to the freelist and
                # would otherwise be counted as "used", permanently wedging the
                # queue after a fill -> delete -> refill cycle. Subtracting the
                # freelist gives the reclaimable, live footprint.
                row = self._conn.execute(
                    "SELECT (page_count - freelist_count) * page_size "
                    "FROM pragma_page_count(), pragma_freelist_count(), pragma_page_size()"
                ).fetchone()
                current_bytes = row[0] if row and row[0] is not None else 0
                current_bytes = max(current_bytes, 0)
                if current_bytes + len(record.payload.encode()) > self._capacity_bytes:
                    self._conn.execute("ROLLBACK")
                    _logger.error(
                        "PersistentStorage: capacity exceeded (%d bytes used, limit %d)",
                        current_bytes,
                        self._capacity_bytes,
                    )
                    return False

                self._conn.execute(
                    """INSERT INTO durable_records
                       (schema_version, tenant_id, agent_id, agentic_user_id,
                        use_s2s_endpoint, payload, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.schema_version,
                        record.tenant_id,
                        record.agent_id,
                        record.agentic_user_id,
                        int(record.use_s2s_endpoint),
                        record.payload,
                        record.created_at,
                    ),
                )
                self._conn.execute("COMMIT")
                return True
            except sqlite3.Error as exc:
                _logger.error("PersistentStorage.store failed: %s", exc)
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                return False

    def claim(self, limit: int, lease_seconds: float) -> list[DurableRecord]:
        """Atomically lease up to *limit* unleased records."""
        with self._lock:
            try:
                now = time.time()
                expire_before = now - self._retention_seconds
                lease_until = now + lease_seconds

                self._conn.execute("BEGIN IMMEDIATE")

                # Prune expired rows inside the same transaction
                self._conn.execute(
                    "DELETE FROM durable_records WHERE created_at < ?",
                    (expire_before,),
                )

                records: list[DurableRecord] = []
                claimed_ids: set[int] = set()
                while len(records) < limit:
                    select_sql = """
                        SELECT id, schema_version, tenant_id, agent_id, agentic_user_id,
                               use_s2s_endpoint, payload, created_at, lease_until, retry_count
                        FROM durable_records
                        WHERE (lease_until IS NULL OR lease_until <= ?)
                          AND created_at >= ?
                    """
                    params: list[object] = [now, expire_before]
                    if claimed_ids:
                        placeholders = ", ".join("?" for _ in claimed_ids)
                        select_sql += f" AND id NOT IN ({placeholders})"
                        params.extend(claimed_ids)
                    select_sql += " ORDER BY created_at LIMIT 1"

                    row = self._conn.execute(select_sql, tuple(params)).fetchone()
                    if row is None:
                        break

                    invalid_reason = self._claim_validation_error(row)
                    if invalid_reason is not None:
                        self._conn.execute(
                            "DELETE FROM durable_records WHERE id = ?",
                            (row[0],),
                        )
                        _logger.warning(
                            "PersistentStorage.claim dropped durable record %s: %s",
                            row[0],
                            invalid_reason,
                        )
                        continue

                    self._conn.execute(
                        "UPDATE durable_records SET lease_until = ? WHERE id = ?",
                        (lease_until, row[0]),
                    )
                    claimed_ids.add(int(row[0]))
                    records.append(
                        DurableRecord(
                            record_id=row[0],
                            schema_version=row[1],
                            tenant_id=row[2],
                            agent_id=row[3],
                            agentic_user_id=row[4],
                            use_s2s_endpoint=bool(row[5]),
                            payload=row[6],
                            created_at=row[7],
                            lease_until=lease_until,
                            retry_count=row[9],
                        )
                    )

                self._conn.execute("COMMIT")
                return records
            except sqlite3.Error as exc:
                _logger.error("PersistentStorage.claim failed: %s", exc)
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                return []

    def delete(self, record_id: int) -> bool:
        """Delete a record by id. Returns False if not found or on error."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute("DELETE FROM durable_records WHERE id = ?", (record_id,))
                found = cur.rowcount > 0
                self._conn.execute("COMMIT")
                return found
            except sqlite3.Error as exc:
                _logger.error("PersistentStorage.delete failed: %s", exc)
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                return False

    @staticmethod
    def _claim_validation_error(row: tuple[object, ...]) -> str | None:
        if row[1] != _SCHEMA_VERSION:
            return f"unsupported schema_version={row[1]!r}"
        if not isinstance(row[2], str) or not row[2].strip():
            return "blank tenant_id"
        if not isinstance(row[3], str) or not row[3].strip():
            return "blank agent_id"
        if not isinstance(row[6], str) or not row[6].strip():
            return "blank payload"
        return None

    def release(self, record_id: int) -> bool:
        """Release a lease so the record becomes claimable again."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "UPDATE durable_records SET lease_until = NULL WHERE id = ?",
                    (record_id,),
                )
                found = cur.rowcount > 0
                self._conn.execute("COMMIT")
                return found
            except sqlite3.Error as exc:
                _logger.error("PersistentStorage.release failed: %s", exc)
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                return False

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                _logger.error("PersistentStorage.close failed: %s", exc)


__all__ = ["DurableRecord", "PersistentStorage"]
