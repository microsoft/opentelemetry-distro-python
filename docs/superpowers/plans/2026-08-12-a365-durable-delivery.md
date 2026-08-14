# Agent365 Durable Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure, standard-library durable store-and-forward delivery to the Python Agent365 exporter so retryable telemetry survives throttling, outages, and process restarts.

**Architecture:** A per-identity transmission gate classifies whether live or replay sends may proceed. A SQLite queue stores serialized request envelopes atomically, and one exporter-owned daemon replay thread resolves fresh tokens and retries leased records. The existing OpenTelemetry `BatchSpanProcessor` remains unchanged.

**Tech Stack:** Python 3.10+, `sqlite3`, `threading`, `pathlib`, `tempfile`, `hashlib`, `json`, `requests`, `pytest`/`unittest`.

## Global Constraints

- Use only the Python standard library for persistence and replay.
- Persistence is enabled by default; `disable_offline_storage=True` opts out.
- Default retention is two days and default capacity is 50 MB.
- POSIX storage directories must be mode `0700`; the database must be mode `0600`.
- Gate state is partitioned by `(tenant_id, agent_id, agentic_user_id, use_s2s_endpoint)`.
- Retryable outcomes are HTTP 401, 408, 429, 5xx, transport errors, and timeouts.
- HTTP 403 and other 4xx outcomes are permanent.
- `SpanExportResult.SUCCESS` means every chunk was delivered or durably stored.
- Do not replace or reimplement OpenTelemetry's `BatchSpanProcessor`.

---

### Task 1: Delivery dispositions and per-identity gate

**Files:**
- Create: `src/microsoft/opentelemetry/a365/core/exporters/durable_delivery.py`
- Create: `tests/a365/test_durable_delivery.py`

**Interfaces:**
- Produces: `DeliveryDisposition`, `DeliveryResult`, `IdentityKey`, and `TransmissionGate`.
- `TransmissionGate.try_acquire(key: IdentityKey) -> bool`
- `TransmissionGate.record_success(key: IdentityKey) -> None`
- `TransmissionGate.record_retryable_failure(key: IdentityKey, retry_after: float | None) -> None`
- `TransmissionGate.release_probe(key: IdentityKey) -> None`

- [ ] **Step 1: Write failing gate tests**

```python
def test_gate_isolates_identities():
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    first = IdentityKey("t1", "a1", None, False)
    second = IdentityKey("t2", "a2", None, False)
    gate.record_retryable_failure(first, retry_after=30)
    assert not gate.try_acquire(first)
    assert gate.try_acquire(second)


def test_gate_allows_only_one_half_open_probe():
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    key = IdentityKey("t1", "a1", None, False)
    gate.record_retryable_failure(key, retry_after=10)
    clock.advance(10)
    assert gate.try_acquire(key)
    assert not gate.try_acquire(key)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_durable_delivery.py -q`

Expected: collection fails because `durable_delivery` does not exist.

- [ ] **Step 3: Implement delivery types and gate**

```python
class DeliveryDisposition(Enum):
    DELIVERED = "delivered"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class DeliveryResult:
    disposition: DeliveryDisposition
    retry_after: float | None = None


@dataclass(frozen=True)
class IdentityKey:
    tenant_id: str
    agent_id: str
    agentic_user_id: str | None
    use_s2s_endpoint: bool
```

Implement a lock-protected dictionary of `_GateState` values. Use
`time.monotonic` and `random.random` as injectable callables. Clamp explicit
`Retry-After` to `[10, 3600]`; otherwise compute full jitter over an exponential
window with a 10-second floor and one-hour cap.

- [ ] **Step 4: Run gate tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_durable_delivery.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\durable_delivery.py tests\a365\test_durable_delivery.py
git commit -m "Add A365 transmission gate" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Secure SQLite durable queue

**Files:**
- Create: `src/microsoft/opentelemetry/a365/core/exporters/persistent_storage.py`
- Create: `tests/a365/test_persistent_storage.py`

**Interfaces:**
- Consumes: `IdentityKey`.
- Produces: `DurableRecord` and `PersistentStorage`.
- `PersistentStorage.store(record: DurableRecord) -> bool`
- `PersistentStorage.claim(limit: int, lease_seconds: float) -> list[DurableRecord]`
- `PersistentStorage.delete(record_id: int) -> bool`
- `PersistentStorage.release(record_id: int) -> bool`
- `PersistentStorage.close() -> None`

- [ ] **Step 1: Write failing storage tests**

```python
def test_store_claim_delete_round_trip(tmp_path):
    storage = PersistentStorage(tmp_path, capacity_bytes=1024 * 1024, retention_seconds=3600)
    record = DurableRecord.new(KEY, "https://example.test", '{"resourceSpans":[]}')
    assert storage.store(record)
    claimed = storage.claim(limit=10, lease_seconds=30)
    assert [item.payload for item in claimed] == [record.payload]
    assert storage.delete(claimed[0].record_id)
    assert storage.claim(limit=10, lease_seconds=30) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_storage_permissions_are_private(tmp_path):
    storage = PersistentStorage(tmp_path / "queue")
    assert stat.S_IMODE((tmp_path / "queue").stat().st_mode) == 0o700
    assert stat.S_IMODE(storage.database_path.stat().st_mode) == 0o600
```

Add tests for expired-record cleanup, capacity rejection, lease release, and
pre-existing POSIX directories owned by another UID using mocked `Path.stat`.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_persistent_storage.py -q`

Expected: collection fails because `persistent_storage` does not exist.

- [ ] **Step 3: Implement storage**

Use one SQLite connection with `check_same_thread=False`, guarded by
`threading.RLock`. Create this schema:

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
)
```

Use `BEGIN IMMEDIATE` when claiming records. Select unleased rows ordered by
`created_at`, update their `lease_until`, then commit. Before inserts, delete
expired rows and reject the insert when `page_count * page_size + payload bytes`
would exceed capacity. Return `False` and log on `sqlite3.Error`; do not swallow
the error as success.

Default directory resolution hashes `getpass.getuser()`, `sys.executable`, and
`Path.cwd()` with SHA-256. Prefer `%LOCALAPPDATA%` on Windows and
`$XDG_STATE_HOME`/`~/.local/state` elsewhere, with `tempfile.gettempdir()` as
the final fallback.

- [ ] **Step 4: Run storage tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_persistent_storage.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\persistent_storage.py tests\a365\test_persistent_storage.py
git commit -m "Add secure A365 persistent storage" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Replay coordinator

**Files:**
- Create: `src/microsoft/opentelemetry/a365/core/exporters/replay_coordinator.py`
- Create: `tests/a365/test_replay_coordinator.py`

**Interfaces:**
- Consumes: `PersistentStorage`, `TransmissionGate`, `DeliveryResult`,
  `Callable[[DurableRecord], DeliveryResult]`.
- Produces: `ReplayCoordinator.start()`, `wake()`, and
  `shutdown(timeout_seconds: float) -> bool`.

- [ ] **Step 1: Write failing replay tests**

```python
def test_replay_deletes_delivered_record():
    storage = FakeStorage([RECORD])
    coordinator = ReplayCoordinator(storage, GATE, send=lambda record: DeliveryResult(DELIVERED))
    coordinator.run_once()
    assert storage.deleted == [RECORD.record_id]


def test_replay_retains_retryable_record_and_updates_gate():
    storage = FakeStorage([RECORD])
    gate = MagicMock()
    coordinator = ReplayCoordinator(
        storage,
        gate,
        send=lambda record: DeliveryResult(RETRYABLE, retry_after=45),
    )
    coordinator.run_once()
    assert storage.released == [RECORD.record_id]
    gate.record_retryable_failure.assert_called_once_with(RECORD.identity, 45)
```

Also test permanent deletion, token resolver exceptions retaining records,
wake-up behavior, and idempotent bounded shutdown.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_replay_coordinator.py -q`

Expected: collection fails because `replay_coordinator` does not exist.

- [ ] **Step 3: Implement coordinator**

Use one daemon `threading.Thread`, a stop `Event`, and a wake `Event`.
`run_once()` claims at most ten records. On delivered/permanent results, delete
the record. On retryable results or exceptions, release the record. Stop the
current pass after a retryable network result so the gate controls subsequent
work, but continue after an identity-specific token resolution exception.

- [ ] **Step 4: Run replay tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_replay_coordinator.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\replay_coordinator.py tests\a365\test_replay_coordinator.py
git commit -m "Add A365 durable replay coordinator" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Integrate durable delivery into the exporter

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/agent365_exporter.py`
- Modify: `tests/a365/test_exporter.py`
- Modify: `tests/a365/test_circuit_breaker.py`
- Create: `tests/a365/test_durable_restart.py`

**Interfaces:**
- Consumes all components from Tasks 1-3.
- `_post_once(url, body, headers) -> DeliveryResult`
- `_persist(identity, url, body) -> bool`
- `_replay_record(record: DurableRecord) -> DeliveryResult`

- [ ] **Step 1: Write failing exporter behavior tests**

```python
def test_retryable_failure_returns_success_when_payload_is_stored():
    exporter = make_exporter()
    exporter._post_once = MagicMock(return_value=DeliveryResult(RETRYABLE, 30))
    exporter._storage = MagicMock()
    exporter._storage.store.return_value = True
    assert exporter.export([_make_span()]) is SpanExportResult.SUCCESS


def test_permanent_failure_is_not_stored():
    exporter = make_exporter()
    exporter._post_once = MagicMock(return_value=DeliveryResult(PERMANENT))
    exporter._storage = MagicMock()
    assert exporter.export([_make_span()]) is SpanExportResult.FAILURE
    exporter._storage.store.assert_not_called()


def test_token_resolver_exception_is_stored_but_empty_token_is_permanent():
    # Use separate exporters to assert exception => stored SUCCESS and None => FAILURE.
```

Add a restart test that stores with exporter A, shuts it down, creates exporter
B on the same storage directory, resolves a fresh token, replays, and empties
the queue.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_exporter.py tests\a365\test_durable_restart.py -q`

Expected: FAIL because exporter construction and HTTP results do not support
durable storage.

- [ ] **Step 3: Replace boolean HTTP helper with classified single-send**

Keep existing logging and SDKStats calls. Return delivered for 2xx, retryable
for 401/408/429/5xx and `requests.RequestException`, and permanent for other
responses. Parse `Retry-After` without sleeping. Remove `_CircuitBreaker` after
moving its half-open behavior to `TransmissionGate`; update its dedicated tests
to cover `TransmissionGate` instead.

- [ ] **Step 4: Wire storage and replay into export**

Build `IdentityKey` from each group, including the first span's
`GEN_AI_AGENT_AUID_KEY`. If the gate rejects a send, persist immediately. If a
send is retryable, update the gate and persist. Wake replay after successful
persistence. Start replay lazily and make `shutdown()` idempotently stop replay,
close storage, and close the requests session.

- [ ] **Step 5: Run exporter and restart tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_exporter.py tests\a365\test_durable_delivery.py tests\a365\test_persistent_storage.py tests\a365\test_replay_coordinator.py tests\a365\test_durable_restart.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\agent365_exporter.py tests\a365
git commit -m "Add durable delivery to A365 exporter" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Wire public options and configuration

**Files:**
- Modify: `src/microsoft/opentelemetry/_constants.py`
- Modify: `src/microsoft/opentelemetry/_distro.py`
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/agent365_exporter_options.py`
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/utils.py`
- Modify: `tests/test_distro.py`
- Modify: `tests/a365/test_handler.py`
- Modify: `README.md`
- Modify: `A365_DOCUMENTATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces public kwargs `a365_exporter_disable_offline_storage` and
  `a365_exporter_storage_directory`.
- Extends `_Agent365Exporter.__init__` with `disable_offline_storage: bool = False`
  and `storage_directory: str | None = None`.

- [ ] **Step 1: Write failing option-forwarding tests**

```python
use_microsoft_opentelemetry(
    enable_a365=True,
    a365_exporter_disable_offline_storage=True,
    a365_exporter_storage_directory="C:\\telemetry",
)
assert kwargs["disable_offline_storage"] is True
assert kwargs["storage_directory"] == "C:\\telemetry"
```

Add equivalent assertions for `Agent365ExporterOptions` and
`create_a365_components`.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_distro.py tests\a365\test_handler.py -q`

Expected: FAIL because the kwargs are not parsed or forwarded.

- [ ] **Step 3: Implement option propagation**

Add constants, pop the kwargs in `use_microsoft_opentelemetry`, forward them to
`_append_a365_components`, and pass them to `_Agent365Exporter`. Extend
`Agent365ExporterOptions` and `create_a365_components` with the same defaults.

- [ ] **Step 4: Document behavior and sensitive-data implications**

Document default persistence, secure path selection, the two new options,
at-least-once replay, the two-day/50-MB limits, and that stored OTLP payloads may
contain prompts or responses when sensitive-data capture is enabled.

- [ ] **Step 5: Run configuration tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_distro.py tests\a365\test_handler.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src\microsoft\opentelemetry\_constants.py src\microsoft\opentelemetry\_distro.py src\microsoft\opentelemetry\a365\core\exporters tests\test_distro.py tests\a365\test_handler.py README.md A365_DOCUMENTATION.md CHANGELOG.md
git commit -m "Expose A365 offline storage options" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Full validation

**Files:**
- Modify only files needed to fix failures introduced by Tasks 1-5.

**Interfaces:**
- Produces a release-ready feature with no new dependency.

- [ ] **Step 1: Run focused A365 tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365 tests\test_distro.py -q`

Expected: PASS.

- [ ] **Step 2: Run static checks used by the repository**

Run: `.venv\Scripts\python.exe -m black --check src tests`

Expected: PASS.

Run: `.venv\Scripts\python.exe -m pylint src\microsoft\opentelemetry\a365 src\microsoft\opentelemetry\_distro.py`

Expected: PASS.

Run: `.venv\Scripts\python.exe -m mypy src\microsoft\opentelemetry\a365`

Expected: PASS.

- [ ] **Step 3: Run the complete test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: PASS.

- [ ] **Step 4: Confirm no dependency was added**

Run: `git --no-pager diff HEAD~5 -- pyproject.toml uv.lock`

Expected: no changes.

- [ ] **Step 5: Commit any validation fixes**

```powershell
git add src tests README.md A365_DOCUMENTATION.md CHANGELOG.md
git commit -m "Validate A365 durable delivery" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
