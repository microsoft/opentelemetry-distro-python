# Backoff Overflow Fix Report

## Defects Fixed

### 1. Backoff Overflow (`durable_delivery.py`)

**Root cause:** `_full_jitter_backoff` computed `2.0 ** failure_count` without
bounding `failure_count`. Python floats are C doubles; exponents ≥ 1024 produce
`OverflowError: Result too large`, permanently crashing any identity that had
accumulated ≥ 1024 consecutive retryable failures.

**Fix (two-layer defence):**

| Layer | Location | Change |
|-------|----------|--------|
| Exponent clamp | `_full_jitter_backoff` | `exponent = min(failure_count, _MAX_BACKOFF_EXPONENT)` before the `2.0**` call |
| Counter saturation | `record_retryable_failure` | `state.failure_count = min(state.failure_count + 1, _MAX_BACKOFF_EXPONENT)` |

**Threshold derivation (no magic numbers):**

```python
_MAX_BACKOFF_EXPONENT = math.ceil(math.log2(_RETRY_AFTER_CAP_SECONDS / _RETRY_AFTER_FLOOR_SECONDS))
# = ceil(log2(3600 / 10)) = ceil(log2(360)) = ceil(8.49) = 9
```

At exponent 9: `10 * 2^9 = 5120 s` → clamped to 3600 s.  
At exponent 10+: already saturated, no change in observable behaviour.

### 2. Replay thread fragility (`replay_coordinator.py`)

**Root cause:** `_run_loop` called `self.run_once()` in a bare `while` loop.
Any exception escaping `run_once` (e.g. a programming bug, an unforeseen
storage error) would propagate, terminate the daemon thread, and silently
disable all future periodic replay — no log, no recovery.

**Fix:** Wrapped the `while … run_once()` inner loop with
`except Exception: _logger.exception(…)`. The outer `while not
self._stop_event.is_set()` continues, so the thread wakes again on the next
periodic cadence. `BaseException` (e.g. `KeyboardInterrupt`,
`SystemExit`) is intentionally **not** caught so shutdown remains clean.

## Regression Tests Added

### `tests/a365/test_durable_delivery.py` (4 new tests)

| Test | Proves |
|------|--------|
| `test_record_retryable_failure_never_raises_beyond_exponent_1024` | 1025 failures never raise |
| `test_backoff_stays_capped_at_3600_seconds_beyond_exponent_1024` | delay ≤ 3600 s after 1025 failures |
| `test_half_open_behavior_preserved_after_high_failure_count` | single probe allowed after 2000 failures |
| `test_failure_count_does_not_grow_unbounded` | `state.failure_count ≤ _MAX_BACKOFF_EXPONENT` after 5000 failures |

### `tests/a365/test_replay_coordinator.py` (1 new test)

| Test | Proves |
|------|--------|
| `test_run_loop_survives_unexpected_exception_from_run_once` | thread delivers record on 2nd pass after injected `RuntimeError` from `run_once` |

## Verification Evidence

```
tests/a365/test_durable_delivery.py  15 passed
tests/a365/test_replay_coordinator.py  18 passed
tests/a365/test_durable_restart.py   2 passed
─────────────────────────────────────────────────
34 passed, 1.59s

tests/a365/ (all non-integration)  396 passed, 11 skipped, 4 subtests passed

pylint  10.00/10  (durable_delivery.py + replay_coordinator.py)
mypy    Success: no issues found in 2 source files
```
