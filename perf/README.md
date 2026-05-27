# Performance benchmarks

This directory contains the regression-gating glue used by the `performance`
CI workflow. The benchmarks themselves live in
[`tests/perf/test_overhead.py`](../tests/perf/test_overhead.py) and are
driven by [`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/).

## Scenarios

| Test | Gating | What it measures |
| --- | --- | --- |
| `test_azure_monitor_span` | yes | `configure_azure_monitor` + `tracer.start_as_current_span` |
| `test_azure_monitor_log`  | yes | `configure_azure_monitor` + `logger.info` |
| `test_otel_span`          | no  | Plain `opentelemetry-sdk` `TracerProvider` reference |
| `test_otel_log`           | no  | Plain `opentelemetry-sdk` `LoggerProvider` reference |

Non-gating scenarios are informational only — they show how much overhead
the distro adds on top of upstream and never fail CI.

The gating flag is attached to each benchmark via
`benchmark.extra_info["gating"]` so `perf/compare.py` can pick it up out of
the pytest-benchmark JSON.

## Running locally

From the repo root, with the distro and dev deps installed
(`pip install -e . && pip install -r dev_requirements.txt`):

```bash
# Run the benchmarks and save the result.
pytest tests/perf --benchmark-only --benchmark-json=pr.json

# Compare against a previously-saved baseline (e.g. from main).
python -m perf.compare --baseline base.json --candidate pr.json --threshold 15
```

`pytest --benchmark-skip` is the default (see `pyproject.toml`), so a normal
`pytest` invocation will *skip* the perf tests entirely. Pass
`--benchmark-only` to opt in.

## CI

`.github/workflows/performance.yml` runs the suite on every pull request:

1. Install the PR branch, run `pytest tests/perf --benchmark-only
   --benchmark-json=pr.json`.
2. Check out the base branch, install it, repeat → `base.json`.
3. `perf/compare.py` produces a markdown report and exits non-zero if any
   *gating* scenario regresses by more than `PERF_REGRESSION_THRESHOLD`
   percent (default 15).
4. The report is posted as a sticky PR comment.
