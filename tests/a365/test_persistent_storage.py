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


# ---------------------------------------------------------------------------
# POSIX permissions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_storage_permissions_are_private(tmp_path):
    storage = PersistentStorage(tmp_path / "queue")
    assert stat.S_IMODE((tmp_path / "queue").stat().st_mode) == 0o700
    assert stat.S_IMODE(storage.database_path.stat().st_mode) == 0o600
    storage.close()


# ---------------------------------------------------------------------------
# Unsafe ownership rejected
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership check")
def test_rejects_directory_owned_by_another_uid(tmp_path):
    from pathlib import Path
    import types

    foreign_uid = os.getuid() + 1

    real_stat = os.stat(tmp_path)
    mock_result = types.SimpleNamespace(
        st_uid=foreign_uid,
        st_mode=real_stat.st_mode,
        st_size=real_stat.st_size,
        st_mtime=real_stat.st_mtime,
    )

    with patch.object(Path, "stat", return_value=mock_result):
        with pytest.raises(PermissionError, match="unsafe ownership"):
            PersistentStorage(tmp_path / "queue_foreign")


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
