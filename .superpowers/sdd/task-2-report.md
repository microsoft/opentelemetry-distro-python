# Task 2 Report: Secure SQLite Durable Queue

## Files Created

| File | Purpose |
|------|---------|
| `src/microsoft/opentelemetry/a365/core/exporters/persistent_storage.py` | Production implementation |
| `tests/a365/test_persistent_storage.py` | Covering test suite |

---

## Schema

```sql
CREATE TABLE IF NOT EXISTS durable_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    agentic_user_id TEXT,
    use_s2s_endpoint INTEGER NOT NULL,
    url TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    lease_until REAL,
    retry_count INTEGER NOT NULL DEFAULT 0
);
```

WAL mode enabled for concurrent readers.

---

## Locking Decisions

- One `sqlite3.Connection` with `check_same_thread=False`, guarded by `threading.RLock`.
- `claim()` uses `BEGIN IMMEDIATE` to ensure atomic read-then-update with no phantom rows.
- All mutations (`store`, `delete`, `release`) hold the `RLock` for the duration.

---

## Default Directory Resolution

`SHA-256(getuser() + sys.executable + cwd)[:16]` is used to create a process-scoped
subdirectory under:

1. `%LOCALAPPDATA%\a365-durable-queue\<hash>` (Windows)
2. `$XDG_STATE_HOME/a365-durable-queue/<hash>` (Linux/macOS with XDG)
3. `~/.local/state/a365-durable-queue/<hash>` (Linux/macOS default)
4. `tempfile.gettempdir()/a365-durable-queue/<hash>` (fallback)

---

## POSIX Security

- Directory created with `0700` via `os.chmod`.
- DB file set to `0600` immediately after creation.
- If directory already exists and `st_uid != os.getuid()`, a `PermissionError("unsafe ownership")` is raised.
- Both checks skipped on Windows (`os.name == "nt"`).

---

## Error Handling

- All `sqlite3.Error` exceptions are caught, logged with `_logger.error`, and the method returns `False`/`[]`.
- Capacity check: before each `store`, expired rows are deleted; if `page_count * page_size + len(payload bytes) > capacity_bytes`, the store returns `False` and logs.

---

## Defaults

| Parameter | Default |
|-----------|---------|
| `capacity_bytes` | 52,428,800 (50 MB) |
| `retention_seconds` | 172,800 (2 days) |

---

## Tests and Output

```
tests/a365/test_persistent_storage.py::test_store_claim_delete_round_trip PASSED
tests/a365/test_persistent_storage.py::test_release_makes_record_claimable_again PASSED
tests/a365/test_persistent_storage.py::test_expired_records_are_cleaned_up PASSED
tests/a365/test_persistent_storage.py::test_store_rejects_when_capacity_exceeded PASSED
tests/a365/test_persistent_storage.py::test_storage_permissions_are_private SKIPPED (POSIX only)
tests/a365/test_persistent_storage.py::test_rejects_directory_owned_by_another_uid SKIPPED (POSIX only)
tests/a365/test_persistent_storage.py::test_claim_respects_limit PASSED
tests/a365/test_persistent_storage.py::test_durable_record_new_fields PASSED
tests/a365/test_persistent_storage.py::test_delete_unknown_record_id PASSED
tests/a365/test_persistent_storage.py::test_release_unknown_record_id PASSED

8 passed, 2 skipped in 2.18s
```

### TDD Compliance

Each test was written before implementation and verified to fail with `ModuleNotFoundError`
(import collection failure) before the production file was created — satisfying the RED step.

---

## Self-Review

| Concern | Assessment |
|---------|------------|
| `BEGIN IMMEDIATE` in `claim` | Correct for write-intent locking; prevents races on concurrent claim calls |
| `page_count * page_size` capacity check | Approximate (reflects allocated pages, not row data sum); conservative since WAL overhead means actual payload fits easily. Acceptable per spec. |
| `check_same_thread=False` + `RLock` | RLock is reentrant (needed if `close()` is called from within a locked context). All public methods hold the lock; no unguarded access. |
| `retention_seconds=0` in test | Triggers immediate expiry; cleanup confirmed via second store asserting no stale data returned |
| Windows POSIX tests skipped | Decorated with `@pytest.mark.skipif(os.name == "nt")` per spec |
| `DurableRecord` is `frozen=True` | Safe to share across threads after construction |
| `record_id=None` for unpersisted records | Clear sentinel; consumers should check before using |

No issues found that require blocking changes.

---

## Commit SHA

`f493aa9`

---

## Review Fix Report (commit `f8de803`)

### Fixes Applied

| Finding | Fix |
|---------|-----|
| Transaction ambiguity | Added `isolation_level=None` to `sqlite3.connect`; all mutations now use explicit `BEGIN IMMEDIATE / COMMIT / ROLLBACK` |
| POSIX directory mode | `_ensure_private_directory` calls `os.chmod(directory, 0o700)` for both new **and** existing directories; existing dirs also get ownership check + mode enforcement |
| Expired rows not pruned in `claim` | Added `DELETE FROM durable_records WHERE created_at < ?` inside the `BEGIN IMMEDIATE` transaction in `claim()` |
| Global `Path.stat` mock | Replaced `patch.object(Path, "stat", ...)` with `patch.object(_mod.os, "stat", ...)` targeting the module-local `os` reference; directory pre-created before patch activates |

### New Tests Added

| Test | Purpose |
|------|---------|
| `test_connection_is_in_autocommit_mode` | Asserts `conn.isolation_level is None` |
| `test_claim_prunes_expired_rows` | Inserts a row with `created_at=0.0`, calls `claim`, asserts row deleted and nothing returned |

### Command and Output

```
$env:PYTHONPATH = "...\.worktrees\a365-durable-delivery\src"
& "...\.venv\Scripts\python.exe" -m pytest tests\a365\test_persistent_storage.py -v -o addopts=

============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.3
collected 12 items

tests/a365/test_persistent_storage.py::test_connection_is_in_autocommit_mode PASSED
tests/a365/test_persistent_storage.py::test_claim_prunes_expired_rows PASSED
tests/a365/test_persistent_storage.py::test_store_claim_delete_round_trip PASSED
tests/a365/test_persistent_storage.py::test_release_makes_record_claimable_again PASSED
tests/a365/test_persistent_storage.py::test_expired_records_are_cleaned_up PASSED
tests/a365/test_persistent_storage.py::test_store_rejects_when_capacity_exceeded PASSED
tests/a365/test_persistent_storage.py::test_storage_permissions_are_private SKIPPED
tests/a365/test_persistent_storage.py::test_rejects_directory_owned_by_another_uid SKIPPED
tests/a365/test_persistent_storage.py::test_claim_respects_limit PASSED
tests/a365/test_persistent_storage.py::test_durable_record_new_fields PASSED
tests/a365/test_persistent_storage.py::test_delete_unknown_record_id PASSED
tests/a365/test_persistent_storage.py::test_release_unknown_record_id PASSED

======================== 10 passed, 2 skipped in 1.12s ========================
```
