# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for PersistentStorage (Task 2)."""

from __future__ import annotations

import os
import stat
import time
from unittest.mock import patch

import pytest

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import IdentityKey
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import (
    DurableRecord,
    PersistentStorage,
)

KEY = IdentityKey(
    tenant_id="t1",
    agent_id="a1",
    agentic_user_id=None,
    use_s2s_endpoint=False,
)


# ---------------------------------------------------------------------------
# Transaction safety: isolation_level=None (autocommit mode)
# ---------------------------------------------------------------------------


def test_connection_is_in_autocommit_mode(tmp_path):
    """The connection must use isolation_level=None so transactions are explicit."""
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    assert storage._conn.isolation_level is None
    storage.close()


# ---------------------------------------------------------------------------
# claim() prunes expired rows during the transaction
# ---------------------------------------------------------------------------


def test_claim_prunes_expired_rows(tmp_path):
    """Expired records stored before a claim call must be deleted by claim itself."""
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=0)
    record = DurableRecord.new(KEY, "https://example.test", '{"stale":true}')
    # Insert directly with a very old created_at so it expires immediately
    import sqlite3 as _sq

    with storage._lock:
        storage._conn.execute("BEGIN IMMEDIATE")
        storage._conn.execute(
            """INSERT INTO durable_records
               (schema_version, tenant_id, agent_id, agentic_user_id,
                use_s2s_endpoint, url, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, "t1", "a1", None, 0, "https://example.test", '{"stale":true}', 0.0),
        )
        storage._conn.execute("COMMIT")

    # claim must prune the expired row and return nothing
    claimed = storage.claim(limit=10, lease_seconds=30)
    assert claimed == []

    # Row must actually be gone
    with storage._lock:
        row = storage._conn.execute("SELECT COUNT(*) FROM durable_records").fetchone()
    assert row[0] == 0
    storage.close()


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_store_claim_delete_round_trip(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    record = DurableRecord.new(KEY, "https://example.test", '{"resourceSpans":[]}')
    assert storage.store(record)
    claimed = storage.claim(limit=10, lease_seconds=30)
    assert [item.payload for item in claimed] == [record.payload]
    assert storage.delete(claimed[0].record_id)
    assert storage.claim(limit=10, lease_seconds=30) == []
    storage.close()


# ---------------------------------------------------------------------------
# Lease release
# ---------------------------------------------------------------------------


def test_release_makes_record_claimable_again(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    record = DurableRecord.new(KEY, "https://example.test", '{"payload":1}')
    assert storage.store(record)

    claimed = storage.claim(limit=10, lease_seconds=30)
    assert len(claimed) == 1

    # While leased, claim returns nothing
    assert storage.claim(limit=10, lease_seconds=30) == []

    # After release the record is available again
    assert storage.release(claimed[0].record_id)
    reclaimed = storage.claim(limit=10, lease_seconds=30)
    assert len(reclaimed) == 1
    assert reclaimed[0].payload == record.payload
    storage.close()


# ---------------------------------------------------------------------------
# Expired-record cleanup
# ---------------------------------------------------------------------------


def test_expired_records_are_cleaned_up(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=0)
    record = DurableRecord.new(KEY, "https://example.test", '{"payload":2}')
    assert storage.store(record)

    # Store a second record to trigger the cleanup path
    record2 = DurableRecord.new(KEY, "https://example.test", '{"payload":3}')
    assert storage.store(record2)

    # Expired records must not be returned by claim
    claimed = storage.claim(limit=10, lease_seconds=30)
    for item in claimed:
        assert item.payload != '{"payload":2}'
    storage.close()


# ---------------------------------------------------------------------------
# Capacity rejection
# ---------------------------------------------------------------------------


def test_store_rejects_when_capacity_exceeded(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1, retention_seconds=3600)
    record = DurableRecord.new(KEY, "https://example.test", "x" * 100)
    # Must return False and not raise
    result = storage.store(record)
    assert result is False
    storage.close()


def test_store_reclaims_capacity_after_fill_delete_refill(tmp_path):
    """Capacity accounting must use live pages, not the file high-water mark.

    Regression: with ``page_count * page_size`` accounting, filling the queue to
    its cap and then claiming/deleting every record left the freed (freelist)
    pages counted as "used", because SQLite does not shrink the file on delete.
    The queue was therefore permanently wedged and rejected all new records.
    Live-page accounting — ``(page_count - freelist_count) * page_size`` — must
    reclaim the freed space so new records can be stored again.
    """
    storage = PersistentStorage(tmp_path, capacity_bytes=64 * 1024, retention_seconds=3600)
    payload = "x" * 4000

    # Fill until the capacity cap rejects a store.
    stored = 0
    while stored < 500 and storage.store(
        DurableRecord.new(KEY, "https://example.test", payload)
    ):
        stored += 1
    # A store was actually rejected (we reached the cap, not the loop guard).
    assert 0 < stored < 500

    # Claim and delete every stored record.
    while True:
        claimed = storage.claim(limit=100, lease_seconds=300)
        if not claimed:
            break
        for rec in claimed:
            assert storage.delete(rec.record_id)

    # The freed space must be reclaimed so new records can be stored again.
    assert storage.store(DurableRecord.new(KEY, "https://example.test", payload)) is True
    storage.close()


# ---------------------------------------------------------------------------
# POSIX permissions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_storage_permissions_are_private(tmp_path):
    storage = PersistentStorage(tmp_path / "queue")
    assert stat.S_IMODE((tmp_path / "queue").stat().st_mode) == 0o700
    assert stat.S_IMODE(storage.database_path.stat().st_mode) == 0o600
    storage.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_wal_and_shm_sidecars_are_private(tmp_path):
    """The DB and its WAL/SHM sidecars must be mode 0600 after journal init.

    WAL mode creates ``queue.db-wal`` and ``queue.db-shm`` sidecars that would
    otherwise inherit the process umask; they can contain the same OTLP payloads
    as the DB and must be locked to the owner.
    """
    storage = PersistentStorage(tmp_path / "queue")
    try:
        for name in ("queue.db", "queue.db-wal", "queue.db-shm"):
            sidecar = tmp_path / "queue" / name
            assert sidecar.exists(), name
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600, name
    finally:
        storage.close()


def test_restrict_file_permissions_locks_db_and_sidecars(tmp_path, monkeypatch):
    """The helper chmods the DB and any existing WAL/SHM sidecars to 0600.

    Runs on Windows (mocks only ``os.chmod``, not ``os.name``, so ``pathlib`` is
    unaffected) to make the sidecar hardening verifiable off-POSIX; the real
    end-to-end modes are checked by the POSIX-only test above.
    """
    import microsoft.opentelemetry.a365.core.exporters.persistent_storage as _mod

    storage = PersistentStorage(tmp_path / "queue")
    try:
        # Journal init created queue.db plus its -wal/-shm sidecars.
        for name in ("queue.db", "queue.db-wal", "queue.db-shm"):
            assert (tmp_path / "queue" / name).exists(), name

        recorded: dict[str, int] = {}
        monkeypatch.setattr(
            _mod.os, "chmod", lambda p, m: recorded.__setitem__(os.path.basename(str(p)), m)
        )
        storage._restrict_file_permissions()

        assert recorded.get("queue.db") == 0o600
        assert recorded.get("queue.db-wal") == 0o600
        assert recorded.get("queue.db-shm") == 0o600
    finally:
        storage.close()


# ---------------------------------------------------------------------------
# Unsafe ownership rejected
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership check")
def test_rejects_directory_owned_by_another_uid(tmp_path):
    import types
    import microsoft.opentelemetry.a365.core.exporters.persistent_storage as _mod

    foreign_uid = os.getuid() + 1

    real_stat = os.lstat(tmp_path)
    mock_result = types.SimpleNamespace(
        st_uid=foreign_uid,
        st_mode=real_stat.st_mode,
        st_size=real_stat.st_size,
        st_mtime=real_stat.st_mtime,
    )

    target_dir = tmp_path / "queue_foreign"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Ownership is validated with a non-symlink-following lstat.
    with patch.object(_mod.os, "lstat", return_value=mock_result):
        with pytest.raises(PermissionError, match="unsafe ownership"):
            PersistentStorage(target_dir)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink rejection")
def test_rejects_symlinked_directory(tmp_path):
    """A symlinked queue directory must be rejected, not silently followed."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    os.symlink(real_dir, link_dir, target_is_directory=True)

    with pytest.raises(PermissionError, match="symlink"):
        PersistentStorage(link_dir)


def test_default_directory_prefers_local_state_even_if_missing(tmp_path):
    """On POSIX without XDG_STATE_HOME, prefer ~/.local/state (to be created)
    rather than falling back to the temp dir merely because it does not exist."""
    import microsoft.opentelemetry.a365.core.exporters.persistent_storage as _mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    local_state = fake_home / ".local" / "state"
    assert not local_state.exists()

    env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
    with patch.object(_mod.sys, "platform", "linux"), patch.dict(
        os.environ, env, clear=True
    ), patch.object(_mod.Path, "home", return_value=fake_home):
        resolved = _mod._resolve_default_directory()

    # The resolved base must be under ~/.local/state, not the temp directory.
    assert str(resolved).startswith(str(local_state))


def test_default_directory_falls_back_to_tmp_when_home_unusable(tmp_path):
    """When the home directory cannot be resolved, fall back to the temp dir."""
    import microsoft.opentelemetry.a365.core.exporters.persistent_storage as _mod

    env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
    with patch.object(_mod.sys, "platform", "linux"), patch.dict(
        os.environ, env, clear=True
    ), patch.object(_mod.Path, "home", side_effect=RuntimeError("no home")):
        resolved = _mod._resolve_default_directory()

    assert str(resolved).startswith(str(_mod.tempfile.gettempdir()))


def test_default_directory_honors_xdg_state_home(tmp_path):
    """XDG_STATE_HOME, when set, takes precedence over ~/.local/state."""
    import microsoft.opentelemetry.a365.core.exporters.persistent_storage as _mod

    xdg = tmp_path / "xdg"
    with patch.object(_mod.sys, "platform", "linux"), patch.dict(
        os.environ, {"XDG_STATE_HOME": str(xdg)}, clear=False
    ):
        resolved = _mod._resolve_default_directory()

    assert str(resolved).startswith(str(xdg))


# ---------------------------------------------------------------------------
# Multiple claims respect limit
# ---------------------------------------------------------------------------


def test_claim_respects_limit(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    for i in range(5):
        storage.store(DurableRecord.new(KEY, "https://example.test", f'{{"i":{i}}}'))

    claimed = storage.claim(limit=3, lease_seconds=30)
    assert len(claimed) == 3
    storage.close()


# ---------------------------------------------------------------------------
# DurableRecord.new round-trips IdentityKey fields
# ---------------------------------------------------------------------------


def test_durable_record_new_fields():
    key = IdentityKey(
        tenant_id="myTenant",
        agent_id="myAgent",
        agentic_user_id="user42",
        use_s2s_endpoint=True,
    )
    rec = DurableRecord.new(key, "https://ep.test", '{"data":1}')
    assert rec.tenant_id == "myTenant"
    assert rec.agent_id == "myAgent"
    assert rec.agentic_user_id == "user42"
    assert rec.use_s2s_endpoint is True
    assert rec.url == "https://ep.test"
    assert rec.payload == '{"data":1}'
    assert rec.record_id is None  # not yet persisted


# ---------------------------------------------------------------------------
# delete returns False for unknown id
# ---------------------------------------------------------------------------


def test_delete_unknown_record_id(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    assert storage.delete(99999) is False
    storage.close()


# ---------------------------------------------------------------------------
# release returns False for unknown id
# ---------------------------------------------------------------------------


def test_release_unknown_record_id(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    assert storage.release(99999) is False
    storage.close()
