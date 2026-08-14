# Agent365 Durable Delivery Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align Python Agent365 durable delivery with the hardened behavioral guarantees in `microsoft/opentelemetry-distro-dotnet#137`.

**Architecture:** Retain the Python SQLite queue and exporter structure, but strengthen their contracts. Add an Agent365-owned batch worker for atomic producer capacity and deterministic lifecycle, persist identity rather than URLs, reconstruct validated HTTPS endpoints during replay, and make retry/replay outcomes explicit and testable.

**Tech Stack:** Python 3.10+, `threading`, `collections.deque`, `sqlite3`, `email.utils`, `requests`, OpenTelemetry SDK, pytest/unittest.

## Global Constraints

- Keep persistence dependency-free and SQLite-backed.
- Preserve the public Agent365 option names and defaults.
- Healthy closed-state sends remain concurrent; only half-open probes are exclusive.
- Positive `Retry-After` values are honored exactly up to 3600 seconds.
- Durable replay never sends credentials over plaintext HTTP.
- `SpanExportResult.SUCCESS` still means every chunk was delivered or durably stored.
- Shutdown must not close exporter resources underneath active export or replay work.
- Every regression begins with a test that fails against commit `822b544`.

---

### Task 1: Retry Timing and Gate State

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/durable_delivery.py`
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/utils.py`
- Test: `tests/a365/test_durable_delivery.py`
- Test: `tests/a365/test_circuit_breaker.py`
- Test: `tests/a365/test_utils.py`

**Interfaces:**
- Produces: `parse_retry_after(headers, now=None) -> float | None`.
- Produces: `TransmissionGate.try_acquire(key) -> bool` where closed-state calls are unrestricted and only an expired backoff grants one probe.

- [ ] **Step 1: Add failing retry parsing tests**

```python
def test_parse_retry_after_http_date():
    now = datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc)
    headers = {"Retry-After": "Fri, 14 Aug 2026 18:00:42 GMT"}
    assert parse_retry_after(headers, now=lambda: now) == 42.0


def test_parse_retry_after_past_date_returns_non_positive():
    now = datetime(2026, 8, 14, 18, 1, tzinfo=timezone.utc)
    headers = {"Retry-After": "Fri, 14 Aug 2026 18:00:42 GMT"}
    assert parse_retry_after(headers, now=lambda: now) == -18.0
```

- [ ] **Step 2: Add failing gate tests**

```python
def test_closed_gate_allows_concurrent_sends():
    gate = TransmissionGate()
    assert gate.try_acquire(KEY)
    assert gate.try_acquire(KEY)


def test_positive_retry_after_is_honored_without_flooring():
    clock = FakeClock()
    gate = TransmissionGate(clock=clock)
    gate.record_retryable_failure(KEY, 1.5)
    clock.advance(1.49)
    assert not gate.try_acquire(KEY)
    clock.advance(0.01)
    assert gate.try_acquire(KEY)


def test_non_positive_retry_after_uses_jitter():
    clock = FakeClock()
    gate = TransmissionGate(clock=clock, random_fn=lambda: 0.5)
    gate.record_retryable_failure(KEY, 0)
    clock.advance(9.99)
    assert not gate.try_acquire(KEY)
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_utils.py tests\a365\test_durable_delivery.py tests\a365\test_circuit_breaker.py -q`

Expected: HTTP-date, closed concurrency, exact positive delay, and non-positive fallback tests fail.

- [ ] **Step 4: Implement date parsing and explicit gate phases**

Use `email.utils.parsedate_to_datetime`. Represent gate state with `blocked_until`, `failure_count`, and `probe_acquired`; do not create state on a healthy `try_acquire`. When `blocked_until == 0`, return `True`. When backoff expires, atomically set `probe_acquired=True`. In `_resolve_retry_delay`, use explicit delay only when `retry_after > 0`; cap it with `min(retry_after, 3600.0)`, otherwise call `_full_jitter_backoff`.

- [ ] **Step 5: Run the focused tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_utils.py tests\a365\test_durable_delivery.py tests\a365\test_circuit_breaker.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\durable_delivery.py src\microsoft\opentelemetry\a365\core\exporters\utils.py tests\a365\test_utils.py tests\a365\test_durable_delivery.py tests\a365\test_circuit_breaker.py
git commit -m "Harden A365 retry timing and transmission gate" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Validated Identity-Only Durable Records

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/persistent_storage.py`
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/agent365_exporter.py`
- Test: `tests/a365/test_persistent_storage.py`
- Test: `tests/a365/test_durable_restart.py`
- Test: `tests/a365/test_exporter.py`

**Interfaces:**
- Changes: `DurableRecord.new(key: IdentityKey, payload: str) -> DurableRecord`.
- Removes: persisted `url`.
- Produces: `PersistentStorage.claim()` that deletes invalid records and returns only schema-valid records.

- [ ] **Step 1: Add failing schema and poison-record tests**

```python
@pytest.mark.parametrize("column,value", [
    ("schema_version", 999),
    ("tenant_id", ""),
    ("agent_id", ""),
    ("payload", ""),
])
def test_claim_deletes_invalid_records_and_continues(storage, column, value):
    invalid_id = insert_raw_record(storage, **{column: value})
    valid = DurableRecord.new(KEY, '{"resourceSpans":[]}')
    assert storage.store(valid)
    claimed = storage.claim(limit=10, lease_seconds=30)
    assert [record.payload for record in claimed] == [valid.payload]
    assert not raw_record_exists(storage, invalid_id)
```

- [ ] **Step 2: Add failing endpoint reconstruction tests**

```python
def test_replay_builds_endpoint_from_record_identity(exporter):
    record = DurableRecord.new(KEY, '{"resourceSpans":[]}')
    exporter._post_once = MagicMock(return_value=DELIVERED_RESULT)
    exporter._replay_record(record)
    sent_url = exporter._post_once.call_args.args[0]
    assert "/tenants/tenant/otlp/agents/agent/traces" in sent_url


def test_plaintext_replay_retains_record_without_sending(exporter, monkeypatch):
    monkeypatch.setattr(exporter, "_domain_override", "http://example.test")
    exporter._post_once = MagicMock()
    with pytest.raises(ReplayEndpointError):
        exporter._replay_record(DurableRecord.new(KEY, "{}"))
    exporter._post_once.assert_not_called()
```

- [ ] **Step 3: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_persistent_storage.py tests\a365\test_durable_restart.py tests\a365\test_exporter.py -q`

Expected: invalid rows are returned, records require URLs, and replay uses persisted URLs.

- [ ] **Step 4: Migrate the SQLite schema safely**

Create schema version 2 without `url`. On initialization, inspect `PRAGMA table_info(durable_records)`; if the legacy `url` column exists, create `durable_records_v2`, copy identity/payload/timestamps, drop the old table, and rename the new table in one `BEGIN IMMEDIATE` transaction. Validate supported schema and non-blank tenant, agent, and payload during `claim`; delete invalid rows in the same transaction.

- [ ] **Step 5: Reconstruct and validate replay endpoints**

Add `ReplayEndpointError` as a retryable replay-stop condition. Build the URL from current `_domain_override or DEFAULT_ENDPOINT_URL` plus record identity. Reject any parsed scheme other than `https` before resolving or attaching the token. Persist only identity and payload.

- [ ] **Step 6: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_persistent_storage.py tests\a365\test_durable_restart.py tests\a365\test_exporter.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\persistent_storage.py src\microsoft\opentelemetry\a365\core\exporters\agent365_exporter.py tests\a365\test_persistent_storage.py tests\a365\test_durable_restart.py tests\a365\test_exporter.py
git commit -m "Validate A365 durable records and replay endpoints" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Replay Terminal-State Accounting

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/replay_coordinator.py`
- Test: `tests/a365/test_replay_coordinator.py`

**Interfaces:**
- Produces: `_delete_record(record, reason) -> bool`.
- Consumes: `ReplayIdentityError` and `ReplayEndpointError` as record-retaining conditions.

- [ ] **Step 1: Add failing deletion and endpoint tests**

```python
def test_delete_failure_after_success_logs_duplicate_risk(caplog):
    storage = FakeStorage([RECORD], delete_result=False)
    coordinator = ReplayCoordinator(storage, GATE, send=lambda _: DELIVERED_RESULT)
    coordinator.run_once()
    assert "duplicate delivery" in caplog.text.lower()


def test_endpoint_error_retains_record_and_stops_pass():
    storage = FakeStorage([RECORD, SECOND_RECORD])
    coordinator = ReplayCoordinator(storage, GATE, send=raise_endpoint_error)
    assert not coordinator.run_once()
    assert storage.released == [RECORD.record_id, SECOND_RECORD.record_id]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_replay_coordinator.py -q`

Expected: delete failure is counted as terminal and endpoint errors use the unexpected-error path.

- [ ] **Step 3: Implement explicit terminal accounting**

Return the result of `storage.delete`. Increment `deleted_count` only on success. Log record ID and duplicate risk after delivered-delete failure. For permanent-delete failure, log that the poison record may recur. Catch `ReplayEndpointError`, release current and remaining records, release the gate probe, and stop the pass.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_replay_coordinator.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\replay_coordinator.py tests\a365\test_replay_coordinator.py
git commit -m "Harden A365 replay terminal accounting" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Export Isolation and Configuration Validation

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/agent365_exporter.py`
- Modify: `src/microsoft/opentelemetry/_distro.py`
- Test: `tests/a365/test_exporter.py`
- Test: `tests/test_distro.py`

**Interfaces:**
- Produces: permanent failure breaks only the current identity's chunk loop.
- Produces: `_validate_a365_batch_options(...) -> None`, called before the broad component-construction handler.

- [ ] **Step 1: Add failing permanent-chunk test**

```python
def test_permanent_first_chunk_stops_identity_but_other_identity_continues(exporter):
    exporter._post_once.side_effect = [PERMANENT_RESULT, DELIVERED_RESULT]
    result = exporter.export(spans_for_two_identities(first_identity_has_two_chunks=True))
    assert result is SpanExportResult.FAILURE
    assert exporter._post_once.call_count == 2
```

- [ ] **Step 2: Add failing public validation tests**

```python
@pytest.mark.parametrize("kwargs", [
    {"max_queue_size": 0},
    {"scheduled_delay_ms": 0},
    {"max_export_batch_size": 0},
    {"max_queue_size": 10, "max_export_batch_size": 11},
])
def test_invalid_a365_batch_configuration_raises(kwargs):
    with pytest.raises(ValueError):
        _append_a365_components(True, {"span_processors": []}, enable_observability_exporter=True, **kwargs)
```

- [ ] **Step 3: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_exporter.py tests\test_distro.py -q`

Expected: later chunks are sent and invalid configuration is swallowed.

- [ ] **Step 4: Implement isolation and validation**

Break the chunk loop after a permanent disposition. Continue the outer identity loop. Validate queue size and delay are at least 1, batch size is at least 1, and batch size does not exceed queue size. Run validation before entering the existing broad `try`.

- [ ] **Step 5: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_exporter.py tests\test_distro.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\agent365_exporter.py src\microsoft\opentelemetry\_distro.py tests\a365\test_exporter.py tests\test_distro.py
git commit -m "Isolate A365 permanent failures and validate batching" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Atomic Agent365 Batch Processor

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/enriching_span_processor.py`
- Test: `tests/a365/test_enriching_span_processor.py`

**Interfaces:**
- Keeps: `_EnrichingBatchSpanProcessor(exporter, max_queue_size, schedule_delay_millis, export_timeout_millis, max_export_batch_size, suppress_invoke_agent_input)`.
- Produces: atomic acceptance, drain-safe shutdown, idempotent exporter shutdown, and force-flush completion accounting.

- [ ] **Step 1: Add failing concurrent capacity test**

Create a blocking fake exporter and use a barrier to call `on_end` from more threads than queue capacity. Assert accepted spans equal exported spans plus explicitly rejected spans; no accepted span is silently evicted.

- [ ] **Step 2: Add failing lifecycle tests**

Add tests named:

```python
def test_shutdown_drains_every_accepted_span(): ...
def test_shutdown_waits_for_active_export_before_exporter_shutdown(): ...
def test_shutdown_timeout_leaves_worker_owning_cleanup(): ...
def test_concurrent_shutdown_calls_exporter_shutdown_once(): ...
def test_on_end_racing_shutdown_never_strands_or_throws(): ...
```

- [ ] **Step 3: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_enriching_span_processor.py -q`

Expected: standard SDK processor silently evicts under the capacity race and does not satisfy lifecycle ordering.

- [ ] **Step 4: Implement the owned worker**

Replace inheritance from SDK `BatchSpanProcessor` with a `SpanProcessor` implementation backed by `deque`, one `Condition`, and explicit counters for queued and active exports. Reserve capacity and enqueue under the same lock. The worker drains up to `max_export_batch_size`, exports outside the lock, then signals flush/shutdown waiters. Shutdown sets `accepting=False`, wakes the worker, and waits; only the worker calls exporter shutdown after queue and active export are empty. Multiple shutdown callers wait on the same completion event. Preserve current enrichment and suppression before atomic enqueue.

- [ ] **Step 5: Run processor tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_enriching_span_processor.py -q`

Expected: PASS.

- [ ] **Step 6: Run distro construction tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_distro.py -q`

Expected: PASS with the same constructor surface.

- [ ] **Step 7: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\enriching_span_processor.py tests\a365\test_enriching_span_processor.py tests\test_distro.py
git commit -m "Add drain-safe A365 batch processing" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Exporter and Replay Shutdown Ownership

**Files:**
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/agent365_exporter.py`
- Modify: `src/microsoft/opentelemetry/a365/core/exporters/replay_coordinator.py`
- Test: `tests/a365/test_exporter.py`
- Test: `tests/a365/test_replay_coordinator.py`
- Test: `tests/a365/test_durable_restart.py`

**Interfaces:**
- Produces: `ReplayCoordinator.shutdown(timeout_seconds: float | None = None) -> bool`.
- Produces: exporter resources close only after replay termination and exactly once.

- [ ] **Step 1: Add failing active-replay shutdown tests**

Use events to block replay inside `_send`. Call exporter shutdown concurrently and assert storage/session remain open until `_send` exits. Add two concurrent shutdown callers and assert storage/session close once.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_exporter.py tests\a365\test_replay_coordinator.py tests\a365\test_durable_restart.py -q`

Expected: exporter closes resources after the fixed five-second join even when replay remains active.

- [ ] **Step 3: Implement cleanup ownership**

Make the processor worker's exporter shutdown unbounded after accepted work drains. Inside exporter shutdown, signal replay and wait until it exits before closing storage/session. Preserve idempotence with a completion event and a single cleanup owner; concurrent callers wait for that event. Do not close resources when a bounded replay wait reports the thread is alive.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\a365\test_exporter.py tests\a365\test_replay_coordinator.py tests\a365\test_durable_restart.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\microsoft\opentelemetry\a365\core\exporters\agent365_exporter.py src\microsoft\opentelemetry\a365\core\exporters\replay_coordinator.py tests\a365\test_exporter.py tests\a365\test_replay_coordinator.py tests\a365\test_durable_restart.py
git commit -m "Make A365 exporter shutdown deterministic" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 7: Validation, Documentation, and PR

**Files:**
- Modify if needed: `README.md`
- Modify if needed: `A365_DOCUMENTATION.md`
- Modify if needed: `CHANGELOG.md`

**Interfaces:**
- Produces: a pushable branch and GitHub PR with parity evidence.

- [ ] **Step 1: Run the affected suite**

Run: `.venv\Scripts\python.exe -m pytest tests\a365 tests\test_distro.py -q`

Expected: PASS, including the Windows retention regression.

- [ ] **Step 2: Run formatting, lint, and typing**

```powershell
.venv\Scripts\python.exe -m black --check src tests
.venv\Scripts\python.exe -m pylint src\microsoft\opentelemetry\a365 src\microsoft\opentelemetry\_distro.py
.venv\Scripts\python.exe -m mypy src\microsoft\opentelemetry\a365
```

Expected: all commands exit 0.

- [ ] **Step 3: Run the complete suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: PASS.

- [ ] **Step 4: Review the complete branch diff**

Run: `git --no-pager diff --check origin/main...HEAD`

Expected: no whitespace errors.

Run a fresh code review against `origin/main...HEAD`; resolve all blocking and should-fix findings.

- [ ] **Step 5: Update documentation if behavior changed**

Document that replay reconstructs current HTTPS endpoints, poison records are discarded, and shutdown drains accepted spans.

- [ ] **Step 6: Commit validation fixes**

```powershell
git add src tests README.md A365_DOCUMENTATION.md CHANGELOG.md
git commit -m "Validate A365 durable delivery hardening" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 7: Push and create the PR**

```powershell
git push -u origin copilot/a365-durable-delivery
gh pr create --repo microsoft/opentelemetry-distro-python --base main --head copilot/a365-durable-delivery --title "Add retry resilience to Agent365 exporter" --body-file <generated-pr-body>
```

The PR body must link `.NET PR #137`, enumerate the parity guarantees, call out SQLite as the intentional implementation difference, and include exact test/lint/type-check results.
