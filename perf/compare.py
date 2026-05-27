# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
"""Compare two pytest-benchmark JSON files and gate on regression.

Reads the JSON produced by ``pytest --benchmark-json=...`` for the base
branch and the PR branch. A scenario "regresses" when its candidate median
operation time is greater than the baseline median by more than
``--threshold`` percent (i.e. slower).

Emits a markdown comparison table on stdout (suitable for posting as a
sticky PR comment). Exits with status ``1`` if any *gating* scenario
regresses past the threshold; non-gating scenarios are reported but never
fail the build.

A scenario is treated as gating when its ``extra_info.gating`` field is
``true`` in either file.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional


def _load_benchmarks(path: str) -> Dict[str, Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    out: Dict[str, Dict[str, Any]] = {}
    for entry in doc.get("benchmarks", []):
        # Strip the conventional ``test_`` prefix so report names match the
        # scenario names used in PR comments.
        name = entry.get("name", "")
        if name.startswith("test_"):
            name = name[len("test_") :]
        out[name] = entry
    return out


def _stats_seconds(entry: Optional[Dict[str, Any]]) -> Optional[float]:
    if not entry:
        return None
    return entry.get("stats", {}).get("median")


def _ops_per_sec(seconds: Optional[float]) -> float:
    if not seconds or seconds <= 0:
        return float("nan")
    return 1.0 / seconds


def _pct_slower(base_s: float, cand_s: float) -> float:
    """Positive number => candidate is slower than baseline (regression)."""
    if base_s <= 0:
        return 0.0
    return (cand_s - base_s) / base_s * 100.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two pytest-benchmark JSON files and gate on regression.")
    parser.add_argument("--baseline", required=True, help="pytest-benchmark JSON for the base branch")
    parser.add_argument("--candidate", required=True, help="pytest-benchmark JSON for the PR branch")
    parser.add_argument("--threshold", type=float, default=15.0, help="Max allowed regression %% (default 15)")
    parser.add_argument("--output", help="Write markdown report to this path in addition to stdout")
    args = parser.parse_args(argv)

    base = _load_benchmarks(args.baseline)
    cand = _load_benchmarks(args.candidate)
    all_names = sorted(set(base) | set(cand))

    lines: list[str] = []
    lines.append("### Performance comparison")
    lines.append("")
    lines.append(
        f"Threshold: regressions >{args.threshold:.1f}% on gating scenarios fail the build. "
        "Higher ops/s is better; positive Δ means the PR is slower."
    )
    lines.append("")
    lines.append("| Scenario | Gating | Baseline (ops/s) | Candidate (ops/s) | Δ % | Status |")
    lines.append("| --- | --- | ---: | ---: | ---: | :---: |")

    any_regression = False
    for name in all_names:
        b = base.get(name)
        c = cand.get(name)
        b_gating = bool(((b or {}).get("extra_info") or {}).get("gating", False))
        c_gating = bool(((c or {}).get("extra_info") or {}).get("gating", False))
        gating = b_gating or c_gating
        b_sec = _stats_seconds(b)
        c_sec = _stats_seconds(c)
        b_ops = _ops_per_sec(b_sec)
        c_ops = _ops_per_sec(c_sec)
        if b_sec is not None and c_sec is not None:
            delta = _pct_slower(b_sec, c_sec)
            regressed = gating and delta > args.threshold
            status = "❌" if regressed else ("⚠️" if delta > args.threshold else "✅")
            if regressed:
                any_regression = True
            lines.append(
                f"| `{name}` | {'yes' if gating else 'no'} | {b_ops:,.1f} | {c_ops:,.1f} | "
                f"{delta:+.2f}% | {status} |"
            )
        else:
            lines.append(
                f"| `{name}` | {'yes' if gating else 'no'} | "
                f"{('—' if b_sec is None else f'{b_ops:,.1f}')} | "
                f"{('—' if c_sec is None else f'{c_ops:,.1f}')} | — | ➖ |"
            )

    report = "\n".join(lines) + "\n"
    sys.stdout.write(report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)

    if any_regression:
        sys.stderr.write(f"\n[compare] FAIL: one or more gating scenarios regressed > {args.threshold:.1f}%\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
