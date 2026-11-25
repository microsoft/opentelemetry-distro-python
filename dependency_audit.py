# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only audit of the committed uv lockfile and Microsoft package feed."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
from multiprocessing import get_context
from multiprocessing.queues import Queue
from pathlib import Path
from queue import Empty
import re
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from packaging.version import Version

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

FEED_URL = "https://packagefeedproxy.microsoft.io/pypi/simple"
ADVISORY_URL = "https://api.osv.dev"
UV_VERSION = "0.11.20"


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    registry: str


@dataclass
class FeedCheck:
    name: str
    version: str
    status: str
    error: str | None = None


@dataclass
class Report:
    schema_version: int = 1
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "failed"
    feed_url: str = FEED_URL
    advisory_url: str = ADVISORY_URL
    scanner_version: str = UV_VERSION
    lock_sha256: str | None = None
    packages: list[LockedPackage] = field(default_factory=list)
    excluded_packages: list[dict[str, str]] = field(default_factory=list)
    feed_checks: list[FeedCheck] = field(default_factory=list)
    artifact_downloads_verified: bool = False
    audit: dict[str, object] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def read_lock(project: Path, report: Report) -> None:
    content = (project / "uv.lock").read_bytes()
    report.lock_sha256 = hashlib.sha256(content).hexdigest()
    lock = tomllib.loads(content.decode("utf-8"))
    if lock.get("version") != 1 or not isinstance(lock.get("package"), list):
        raise ValueError("Unsupported or malformed uv.lock.")
    for package in lock["package"]:
        if not isinstance(package, dict):
            raise ValueError("Invalid package entry in uv.lock.")
        name, version, source = package.get("name"), package.get("version"), package.get("source")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
            or not isinstance(version, str)
            or not isinstance(source, dict)
        ):
            raise ValueError("A locked package has invalid name, version, or source.")
        Version(version)
        registry = source.get("registry")
        if isinstance(registry, str) and registry:
            if registry.rstrip("/") not in (FEED_URL, "https://pypi.org/simple"):
                raise ValueError(f"Unsupported registry for {name}; refusing to send its identity to OSV.")
            report.packages.append(LockedPackage(name, version, registry))
        else:
            report.excluded_packages.append({"name": name, "source": json.dumps(source, sort_keys=True)})
            if source != {"editable": "."}:
                report.errors.append(f"Cannot audit non-registry dependency {name}.")
    report.packages = sorted(
        set(report.packages), key=lambda package: (package.name, package.version, package.registry)
    )
    if not report.packages:
        raise ValueError("No registry dependencies were found in uv.lock.")
    if any(package.registry.rstrip("/") != FEED_URL for package in report.packages):
        report.warnings.append(
            "The existing lockfile references registries outside the Microsoft proxy. "
            "Stage 1 checks feed availability but does not rewrite sources or verify artifact downloads."
        )


def check_feed(package: LockedPackage, timeout: int) -> FeedCheck:
    name = re.sub(r"[-_.]+", "-", package.name).lower()
    request = Request(
        f"{FEED_URL}/{name}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json", "User-Agent": "dependency-audit-pilot/1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            metadata = json.load(response)
        if not isinstance(metadata, dict):
            raise ValueError("Feed metadata is not a JSON object.")
        versions = metadata.get("versions")
        if not isinstance(versions, list) or any(not isinstance(version, str) for version in versions):
            raise ValueError("Feed metadata does not contain a valid version list.")
        parsed_versions = set()
        for version in versions:
            try:
                parsed_versions.add(Version(version))
            except ValueError:
                continue
        if versions and not parsed_versions:
            raise ValueError("Feed metadata does not contain any PEP 440 versions.")
        if Version(package.version) not in parsed_versions:
            return FeedCheck(package.name, package.version, "missing", "Locked version is not listed in the feed.")
        return FeedCheck(package.name, package.version, "available")
    except (OSError, URLError, HTTPException, ValueError) as error:
        return FeedCheck(package.name, package.version, "failed", str(error))


def feed_worker(packages: list[LockedPackage], network_timeout: int, results: Queue[FeedCheck]) -> None:
    with ThreadPoolExecutor(max_workers=6) as executor:
        for check in executor.map(lambda package: check_feed(package, network_timeout), packages):
            results.put(check)


def verify_feed(packages: list[LockedPackage], network_timeout: int, feed_timeout: int) -> list[FeedCheck]:
    context = get_context("spawn")
    results: Queue[FeedCheck] = context.Queue()
    worker = context.Process(target=feed_worker, args=(packages, network_timeout, results))
    checks: list[FeedCheck] = []
    deadline = time.monotonic() + feed_timeout
    try:
        worker.start()
        for _ in packages:
            checks.append(results.get(timeout=max(0, deadline - time.monotonic())))
    except Empty:
        # executor.map returns results in input order, including duplicate versions from different registries.
        checks.extend(
            FeedCheck(package.name, package.version, "failed", "Feed phase did not complete before its deadline.")
            for package in packages[len(checks) :]
        )
    finally:
        if worker.pid is not None:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=5)
        results.close()
    return checks


def run_uv(project: Path, arguments: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", *arguments],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def audit_lock(project: Path, report: Report, timeout: int) -> None:
    deadline = time.monotonic() + timeout

    def remaining_timeout() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("uv audit", timeout)
        return remaining

    version = run_uv(project, ["--version"], remaining_timeout())
    if version.returncode or not version.stdout.startswith(f"uv {UV_VERSION} "):
        raise ValueError(f"Install the pinned uv {UV_VERSION} from .github/dependency-audit-requirements.txt.")
    check = run_uv(project, ["lock", "--check", "--offline"], remaining_timeout())
    if check.returncode:
        raise ValueError(f"Lockfile consistency check failed: {check.stderr.strip()}")
    result = run_uv(
        project,
        [
            "audit",
            "--frozen",
            "--output-format",
            "json",
            "--service-format",
            "osv",
            "--service-url",
            ADVISORY_URL,
            "--preview-features",
            "audit-command,json-output",
        ],
        remaining_timeout(),
    )
    if result.returncode not in (0, 1):
        raise ValueError(f"uv audit failed ({result.returncode}): {result.stderr.strip()}")
    try:
        audit = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError(f"uv audit did not return valid JSON: {result.stderr.strip()}") from error
    if not isinstance(audit, dict):
        raise ValueError("uv audit did not return a JSON object.")
    report.audit = audit
    summary = audit.get("summary")
    vulnerabilities, adverse_statuses = audit.get("vulnerabilities"), audit.get("adverse_statuses")
    if (
        not isinstance(summary, dict)
        or not isinstance(vulnerabilities, list)
        or not isinstance(adverse_statuses, list)
        or any(not isinstance(item, dict) for item in vulnerabilities + adverse_statuses)
        or any(
            not isinstance(summary.get(key), int) or isinstance(summary[key], bool) or summary[key] < 0
            for key in ("audited_packages", "vulnerabilities", "adverse_statuses")
        )
    ):
        raise ValueError("uv audit returned an unsupported or incomplete JSON schema.")
    expected = len({(package.name, package.version) for package in report.packages})
    if summary["audited_packages"] != expected:
        raise ValueError(f"Incomplete audit coverage: expected {expected} packages, got {summary['audited_packages']}.")
    if summary["vulnerabilities"] != len(vulnerabilities) or summary["adverse_statuses"] != len(adverse_statuses):
        raise ValueError("uv audit summary does not match its findings.")
    has_findings = bool(vulnerabilities or adverse_statuses)
    if result.returncode != int(bool(vulnerabilities)):
        raise ValueError(f"uv audit exit code disagrees with its findings: {result.stderr.strip()}")
    report.status = "findings" if has_findings else "clean"


def scan(project: Path, network_timeout: int = 30, audit_timeout: int = 600, feed_timeout: int = 300) -> Report:
    report = Report()
    paths = [project / "pyproject.toml", project / "uv.lock"]
    snapshots: dict[Path, bytes] = {}
    try:
        snapshots = {path: path.read_bytes() for path in paths}
        read_lock(project, report)
        if report.errors:
            return report
    except (OSError, ValueError) as error:
        report.errors.append(f"Cannot read audit inputs: {error}")
        return report
    try:
        report.feed_checks = verify_feed(report.packages, network_timeout, feed_timeout)
    except OSError as error:
        report.errors.append(f"Cannot start feed verification: {error}")
    for check in report.feed_checks:
        if check.status != "available":
            report.errors.append(f"Feed verification failed for {check.name}=={check.version}: {check.error}")
    try:
        audit_lock(project, report, audit_timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report.errors.append(f"Audit failed: {error}")
    for path, content in snapshots.items():
        try:
            if path.read_bytes() != content:
                report.errors.append(f"Read-only invariant violated: {path.name} changed during the audit.")
        except OSError as error:
            report.errors.append(f"Cannot verify read-only invariant for {path.name}: {error}")
    if report.errors:
        report.status = "failed"
    return report


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Value must be a positive integer.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=Path("dependency-audit-report.json"))
    parser.add_argument("--network-timeout", type=positive_integer, default=30)
    parser.add_argument("--feed-timeout", type=positive_integer, default=300)
    parser.add_argument("--audit-timeout", type=positive_integer, default=600)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    output = args.output.resolve()
    protected = [(project / name).resolve() for name in ("pyproject.toml", "uv.lock")]
    protected.append(Path(__file__).resolve())
    if output in protected or output.is_relative_to((project / ".git").resolve()):
        print("Refusing to overwrite an audit input or Git metadata.", file=sys.stderr)
        return 2
    report = scan(project, args.network_timeout, args.audit_timeout, args.feed_timeout)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"Cannot write audit report: {error}", file=sys.stderr)
        return 2
    print(f"Dependency audit: {report.status}; {len(report.packages)} locked packages. Report: {output}")
    for message in report.warnings:
        print(f"Warning: {message}", file=sys.stderr)
    for message in report.errors:
        print(f"Error: {message}", file=sys.stderr)
    if report.status == "failed":
        return 2
    return 1 if report.status == "findings" else 0


if __name__ == "__main__":
    sys.exit(main())
