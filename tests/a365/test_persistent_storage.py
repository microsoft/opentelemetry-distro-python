# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Agent365's adapter to Azure Monitor offline storage."""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest
from azure.monitor.opentelemetry.exporter._storage import LocalFileStorage, StorageExportResult

from microsoft.opentelemetry.a365.core.exporters.durable_delivery import IdentityKey
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import DurableRecord, PersistentStorage

KEY = IdentityKey("tenant", "agent", "user", False)
MODULE = "microsoft.opentelemetry.a365.core.exporters.persistent_storage"


def _record(payload='{"resourceSpans":[]}'):
    return DurableRecord.new(KEY, payload)


def test_uses_real_azure_monitor_provider_in_isolated_namespace(tmp_path):
    storage = PersistentStorage(tmp_path)
    try:
        assert isinstance(storage._provider, LocalFileStorage)
        assert storage.directory == tmp_path / "a365"
        assert storage.store(_record())
        files = list(storage.directory.glob("*.blob"))
        assert len(files) == 1
        envelope = json.loads(files[0].read_text(encoding="utf-8"))
        assert envelope["payload"] == _record().payload
        assert envelope["tenant_id"] == "tenant"
        assert "url" not in envelope
        assert not (tmp_path / "queue.db").exists()
    finally:
        storage.close()


def test_same_root_does_not_mix_azure_monitor_and_agent365_records(tmp_path):
    monitor = LocalFileStorage(str(tmp_path))
    try:
        assert monitor.put([{"azure_monitor": True}], lease_period=0) == StorageExportResult.LOCAL_FILE_BLOB_SUCCESS
        with PersistentStorage(tmp_path) as storage:
            assert not storage.claim(10, 30)
            assert storage.store(_record())
            assert [blob.get() for blob in monitor.gets()] == [({"azure_monitor": True},)]
            assert len(storage.claim(10, 30)) == 1
    finally:
        monitor.close()


def test_restart_replays_same_identity_and_payload(tmp_path):
    original = _record()
    with PersistentStorage(tmp_path) as storage:
        assert storage.store(original)
    with PersistentStorage(tmp_path) as restarted:
        records = restarted.claim(10, 30)
        assert len(records) == 1
        assert replace(records[0], record_id=None, lease_until=None) == original
        assert restarted.delete(records[0].record_id)
        assert not restarted.claim(10, 30)


def test_leases_coordinate_two_instances_and_release(tmp_path):
    with PersistentStorage(tmp_path) as first, PersistentStorage(tmp_path) as second:
        assert first.store(_record())
        claimed = first.claim(10, 30)
        assert len(claimed) == 1
        assert not second.claim(10, 30)
        assert first.release(claimed[0].record_id)
        reclaimed = second.claim(10, 30)
        assert len(reclaimed) == 1
        assert second.delete(reclaimed[0].record_id)
        assert not first.claim(10, 30)


def test_expired_lease_survives_restart(tmp_path):
    with PersistentStorage(tmp_path) as storage:
        assert storage.store(_record())
        assert len(storage.claim(1, 0)) == 1
    with PersistentStorage(tmp_path) as restarted:
        assert len(restarted.claim(1, 30)) == 1


def test_claim_limit_and_unknown_handles(tmp_path):
    with PersistentStorage(tmp_path) as storage:
        for i in range(5):
            assert storage.store(_record(str(i)))
        assert len(storage.claim(3, 30)) == 3
        assert len(storage.claim(3, 30)) == 2
        assert not storage.delete(-1)
        assert not storage.release(-1)


def test_retention_discards_stale_records(tmp_path):
    with PersistentStorage(tmp_path, retention_seconds=10) as storage:
        assert storage.store(replace(_record("stale"), created_at=time.time() - 100))
        assert storage.store(_record("live"))
        assert [r.payload for r in storage.claim(10, 30)] == ["live"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": 999},
        {"tenant_id": ""},
        {"agent_id": " "},
        {"payload": ""},
        {"created_at": "invalid"},
        {"created_at": float("inf")},
        {"use_s2s_endpoint": "false"},
        {"agentic_user_id": {}},
    ],
)
def test_invalid_envelope_is_logged_and_dropped_without_blocking_valid_records(tmp_path, caplog, overrides):
    with PersistentStorage(tmp_path) as storage:
        envelope = asdict(_record())
        envelope.update(overrides)
        assert storage._provider.put([envelope], lease_period=0) == StorageExportResult.LOCAL_FILE_BLOB_SUCCESS
        assert storage.store(_record("valid"))
        assert [r.payload for r in storage.claim(1, 30)] == ["valid"]
        assert "dropped invalid durable record" in caplog.text
        assert not storage.claim(1, 30)


def test_unreadable_blob_is_logged_and_retained_until_expiry(tmp_path, caplog):
    with PersistentStorage(tmp_path) as storage:
        assert storage.store(_record())
        blob = next(storage.directory.glob("*.blob"))
        blob.write_text("not json", encoding="utf-8")
        assert not storage.claim(1, 30)
        assert "failed to read durable record" in caplog.text
        assert len(list(storage.directory.iterdir())) == 1


def test_transient_read_failure_never_deletes_undelivered_telemetry(tmp_path, caplog):
    with PersistentStorage(tmp_path) as storage:
        assert storage.store(_record("retained"))
        with patch("builtins.open", side_effect=PermissionError("temporary read failure")):
            assert not storage.claim(1, 30)
        assert "failed to read durable record" in caplog.text
        assert len(list(storage.directory.iterdir())) == 1
        assert [r.payload for r in storage.claim(1, 30)] == ["retained"]


def test_capacity_is_reclaimed_after_delete(tmp_path, caplog):
    with PersistentStorage(tmp_path, capacity_bytes=1024) as storage:
        count = 0
        while count < 100 and storage.store(_record("x" * 400)):
            count += 1
        assert 0 < count < 100
        assert "PersistentStorage.store failed" in caplog.text
        for record in storage.claim(100, 30):
            assert storage.delete(record.record_id)
        assert storage.store(_record("x" * 400))


def test_oversized_record_is_rejected(tmp_path, caplog):
    with PersistentStorage(tmp_path, capacity_bytes=1) as storage:
        assert not storage.store(_record())
        assert "capacity" in caplog.text
        assert not list(storage.directory.iterdir())


@pytest.mark.parametrize("result", [StorageExportResult.CLIENT_STORAGE_DISABLED, "disk full"])
def test_upstream_write_failure_is_logged(tmp_path, caplog, result):
    with PersistentStorage(tmp_path) as storage:
        with patch.object(storage._provider, "put", return_value=result):
            assert not storage.store(_record())
        assert "PersistentStorage.store failed" in caplog.text


def test_silent_upstream_delete_failure_is_reported(tmp_path, caplog):
    with PersistentStorage(tmp_path) as storage:
        assert storage.store(_record())
        claimed = storage.claim(1, 30)
        with patch("azure.monitor.opentelemetry.exporter._storage.os.remove", side_effect=PermissionError("denied")):
            assert not storage.delete(claimed[0].record_id)
        assert "PersistentStorage.delete failed" in caplog.text
        assert storage.delete(claimed[0].record_id)


def test_provider_setup_failure_raises_for_exporter_nonfatal_disable(tmp_path):
    with patch(
        "azure.monitor.opentelemetry.exporter._storage.LocalFileStorage._check_and_set_folder_permissions",
        return_value=False,
    ):
        with pytest.raises(OSError, match="Azure Monitor"):
            PersistentStorage(tmp_path)


@pytest.mark.parametrize("root", ["", "  ", 123])
def test_invalid_configuration_is_rejected_at_storage_initialization(root):
    with pytest.raises(ValueError, match="storage_directory"):
        PersistentStorage(root)


def test_file_root_fails_without_fallback(tmp_path):
    root = tmp_path / "file"
    root.write_text("unchanged", encoding="utf-8")
    with pytest.raises(OSError, match="Azure Monitor"):
        PersistentStorage(root)
    assert root.read_text(encoding="utf-8") == "unchanged"


def test_default_directory_uses_azure_monitor_resolver(tmp_path):
    with patch(f"{MODULE}._get_storage_directory", return_value=str(tmp_path / "default")) as resolve:
        with PersistentStorage() as storage:
            assert storage.directory == tmp_path / "default"
            assert storage.store(_record())
        resolve.assert_called_once_with("agent365")


def test_does_not_open_or_migrate_sqlite_backlogs(tmp_path, caplog):
    database = tmp_path / "queue.db"
    database.write_bytes(b"old SQLite backlog")
    with PersistentStorage(tmp_path) as storage:
        assert not storage.claim(10, 30)
        assert storage.store(_record())
    assert database.read_bytes() == b"old SQLite backlog"
    assert "Legacy Agent365 SQLite backlog" in caplog.text


@pytest.mark.skipif(os.name == "nt", reason="Unix filesystem permissions")
@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_real_unix_permissions_come_from_provider_without_changing_parent(tmp_path, mask):
    parent_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    previous = os.umask(mask)
    try:
        with PersistentStorage(tmp_path) as storage:
            assert storage.store(_record())
            assert stat.S_IMODE(storage.directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(next(storage.directory.glob("*.blob")).stat().st_mode) == 0o600
            assert stat.S_IMODE(tmp_path.stat().st_mode) == parent_mode
    finally:
        os.umask(previous)


@pytest.mark.skipif(os.name == "nt", reason="Unix provider permissions")
def test_provider_repairs_existing_owned_cache_but_not_configured_parent(tmp_path):
    tmp_path.chmod(0o750)
    cache = tmp_path / "a365"
    cache.mkdir()
    cache.chmod(0o755)
    with PersistentStorage(tmp_path) as storage:
        assert storage.store(_record())
        assert stat.S_IMODE(cache.stat().st_mode) == 0o700
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o750


@pytest.mark.skipif(os.name == "nt", reason="Unix provider symlink protection")
def test_provider_rejects_symlinked_cache_without_changing_target(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o755)
    (tmp_path / "a365").symlink_to(target, target_is_directory=True)
    before = target.stat().st_mode
    with pytest.raises(OSError, match="Azure Monitor"):
        PersistentStorage(tmp_path)
    assert target.stat().st_mode == before
    assert not list(target.iterdir())


@pytest.mark.skipif(os.name != "nt", reason="Windows provider ACLs")
def test_windows_uses_upstream_acl_handling(tmp_path):
    with patch("azure.monitor.opentelemetry.exporter._storage.subprocess.run") as run:
        run.return_value.returncode = 0
        with PersistentStorage(tmp_path) as storage:
            assert storage.store(_record())
        args = run.call_args.args[0]
        assert Path(args[0]).name == "icacls.exe"
        assert args[1] == str(tmp_path / "a365")
        assert "/inheritance:r" in args
        assert "/grant" in args
