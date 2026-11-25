# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only dependency audit and reporting contracts."""

import io
from http.client import IncompleteRead
import json
from queue import Empty
import subprocess
from unittest.mock import Mock
from urllib.error import URLError

import pytest

import dependency_audit as audit


@pytest.fixture(name="project")
def _project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1.0"\n', encoding="utf-8")
    (tmp_path / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "requests"\nversion = "2.32.5"\n'
        f'source = {{ registry = "{audit.FEED_URL}" }}\n'
        '[[package]]\nname = "example"\nversion = "1.0"\nsource = { editable = "." }\n',
        encoding="utf-8",
    )
    return tmp_path


def _audit_json(count=1, findings=False):
    return {
        "schema": {"version": "preview"},
        "summary": {"audited_packages": count, "vulnerabilities": int(findings), "adverse_statuses": 0},
        "vulnerabilities": [{"id": "GHSA-example", "fix_versions": ["2.32.5"]}] if findings else [],
        "adverse_statuses": [],
    }


@pytest.fixture(name="successful_checks")
def _successful_checks(monkeypatch):
    calls = []

    def run_uv(project, arguments, timeout):
        calls.append(arguments)
        if arguments == ["--version"]:
            return subprocess.CompletedProcess(arguments, 0, f"uv {audit.UV_VERSION} (test)", "")
        if arguments[0] == "lock":
            return subprocess.CompletedProcess(arguments, 0, "", "")
        return subprocess.CompletedProcess(arguments, 0, json.dumps(_audit_json()), "")

    monkeypatch.setattr(audit, "run_uv", run_uv)
    monkeypatch.setattr(
        audit, "check_feed", lambda package, timeout: audit.FeedCheck(package.name, package.version, "available")
    )
    monkeypatch.setattr(
        audit,
        "verify_feed",
        lambda packages, network_timeout, feed_timeout: [
            audit.check_feed(package, network_timeout) for package in packages
        ],
    )
    return calls


def test_scan_is_read_only_and_reports_complete_coverage(project, successful_checks):
    before = {name: (project / name).read_bytes() for name in ("pyproject.toml", "uv.lock")}
    report = audit.scan(project)
    assert report.status == "clean"
    assert len(report.packages) == len(report.feed_checks) == 1
    assert report.lock_sha256
    assert report.excluded_packages == [{"name": "example", "source": '{"editable": "."}'}]
    assert not report.artifact_downloads_verified
    assert not report.errors
    assert successful_checks[1] == ["lock", "--check", "--offline"]
    assert "--frozen" in successful_checks[2]
    assert "--service-url" in successful_checks[2]
    assert audit.ADVISORY_URL in successful_checks[2]
    assert not any("--fix" in call or "--upgrade" in call for call in successful_checks)
    assert before == {name: (project / name).read_bytes() for name in before}


def test_inventory_keeps_alternative_versions_and_warns_about_public_sources(project):
    with (project / "uv.lock").open("a", encoding="utf-8") as lock:
        lock.write(
            '[[package]]\nname = "requests"\nversion = "2.20.0"\nsource = { registry = "https://pypi.org/simple" }\n'
        )
    report = audit.Report()
    audit.read_lock(project, report)
    assert [package.version for package in report.packages] == ["2.20.0", "2.32.5"]
    assert "does not rewrite" in report.warnings[0]


def test_non_registry_dependency_is_explicitly_incomplete(project, monkeypatch):
    with (project / "uv.lock").open("a", encoding="utf-8") as lock:
        lock.write(
            '[[package]]\nname = "private"\nversion = "1.0"\nsource = { git = "https://example.invalid/repo" }\n'
        )
    monkeypatch.setattr(audit, "run_uv", lambda *args: pytest.fail("Unsupported identities must not be sent to OSV"))
    monkeypatch.setattr(audit, "check_feed", lambda *args: pytest.fail("Unsupported inputs must not trigger requests"))
    report = audit.scan(project)
    assert report.status == "failed"
    assert any("non-registry dependency private" in error for error in report.errors)
    assert report.audit is None


def test_private_registry_is_not_sent_to_advisory_service(project, monkeypatch):
    lock = project / "uv.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(audit.FEED_URL, "https://private.invalid/simple"), encoding="utf-8"
    )
    monkeypatch.setattr(
        audit, "run_uv", lambda *args: pytest.fail("Private package identities must not be sent to OSV")
    )
    report = audit.scan(project)
    assert report.status == "failed"
    assert "Unsupported registry" in report.errors[0]
    assert not report.packages


@pytest.mark.parametrize(
    "content",
    [
        "not toml",
        "version = 2\npackage = []\n",
        "version = 1\npackage = []\n",
        'version = 1\npackage = ["invalid"]\n',
        'version = 1\n[[package]]\nname = "bad/name"\nversion = "1.0"\nsource = {}\n',
        'version = 1\n[[package]]\nname = "example"\nversion = "not-a-version"\nsource = {}\n',
    ],
)
def test_invalid_lock_is_reported_without_running_auditor(project, monkeypatch, content):
    (project / "uv.lock").write_text(content, encoding="utf-8")
    monkeypatch.setattr(audit, "run_uv", lambda *args: pytest.fail("Auditor must not run"))
    report = audit.scan(project)
    assert report.status == "failed"
    assert report.errors[0].startswith("Cannot read audit inputs:")


def test_missing_lock_produces_failure_report(project, tmp_path, capsys):
    (project / "uv.lock").unlink()
    output = tmp_path / "report.json"
    assert audit.main(["--project", str(project), "--output", str(output)]) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["errors"]
    assert "Error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "metadata,status",
    [
        ({"versions": ["2.32.5"]}, "available"),
        ({"versions": ["2.32.5.0"]}, "available"),
        ({"versions": ["2.20.0"]}, "missing"),
        ({"versions": []}, "missing"),
        ({"files": []}, "failed"),
        ({"versions": [123]}, "failed"),
        ({"versions": ["invalid"]}, "failed"),
        ([], "failed"),
    ],
)
def test_feed_metadata_and_pep440_version_comparison(monkeypatch, metadata, status):
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(json.dumps(metadata).encode())

    monkeypatch.setattr(audit, "urlopen", urlopen)
    result = audit.check_feed(audit.LockedPackage("Some_Package.Name", "2.32.5", audit.FEED_URL), 17)
    assert result.status == status
    assert requests[0][0].full_url == f"{audit.FEED_URL}/some-package-name/"
    assert requests[0][1] == 17
    assert requests[0][0].get_header("Accept") == "application/vnd.pypi.simple.v1+json"
    if status != "available":
        assert result.error


@pytest.mark.parametrize(
    "error", [URLError("offline"), TimeoutError("timed out"), ValueError("invalid JSON"), IncompleteRead(b"truncated")]
)
def test_feed_failures_are_not_success_shaped(monkeypatch, error):
    def urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr(audit, "urlopen", urlopen)
    result = audit.check_feed(audit.LockedPackage("requests", "2.32.5", audit.FEED_URL), 30)
    assert result.status == "failed"
    assert result.error is not None
    assert str(error) in result.error


def test_feed_failure_retains_audit_findings(project, monkeypatch, successful_checks):
    original = audit.run_uv

    def run_uv(project, arguments, timeout):
        if arguments[0] == "audit":
            return subprocess.CompletedProcess(arguments, 1, json.dumps(_audit_json(findings=True)), "")
        return original(project, arguments, timeout)

    monkeypatch.setattr(audit, "run_uv", run_uv)
    monkeypatch.setattr(
        audit,
        "check_feed",
        lambda package, timeout: audit.FeedCheck(package.name, package.version, "missing", "blocked"),
    )
    report = audit.scan(project)
    assert report.status == "failed"
    assert report.audit is not None
    assert report.audit["vulnerabilities"]
    assert "blocked" in report.errors[0]


@pytest.mark.parametrize(
    "result,message",
    [
        (subprocess.CompletedProcess([], 2, "", "service offline"), "uv audit failed"),
        (subprocess.CompletedProcess([], 1, "", "scanner failed"), "valid JSON"),
        (subprocess.CompletedProcess([], 0, "[]", ""), "JSON object"),
        (subprocess.CompletedProcess([], 0, "{}", ""), "incomplete JSON schema"),
        (subprocess.CompletedProcess([], 0, json.dumps(_audit_json(count=0)), ""), "Incomplete audit coverage"),
        (subprocess.CompletedProcess([], 1, json.dumps(_audit_json()), ""), "exit code disagrees"),
        (subprocess.CompletedProcess([], 0, json.dumps(_audit_json(findings=True)), ""), "exit code disagrees"),
    ],
)
def test_scanner_failures_and_incomplete_results(project, monkeypatch, successful_checks, result, message):
    original = audit.run_uv
    monkeypatch.setattr(
        audit,
        "run_uv",
        lambda project, arguments, timeout: (
            result if arguments[0] == "audit" else original(project, arguments, timeout)
        ),
    )
    report = audit.scan(project)
    assert report.status == "failed"
    assert message in report.errors[-1]


@pytest.mark.parametrize(
    "summary_key,value", [("audited_packages", True), ("vulnerabilities", -1), ("adverse_statuses", "0")]
)
def test_invalid_summary_counts_fail(project, monkeypatch, successful_checks, summary_key, value):
    data = _audit_json()
    data["summary"][summary_key] = value
    original = audit.run_uv
    monkeypatch.setattr(
        audit,
        "run_uv",
        lambda project, arguments, timeout: (
            subprocess.CompletedProcess(arguments, 0, json.dumps(data), "")
            if arguments[0] == "audit"
            else original(project, arguments, timeout)
        ),
    )
    assert audit.scan(project).status == "failed"


@pytest.mark.parametrize("failure", ["version", "stale", "timeout", "missing-tool"])
def test_tooling_and_lock_check_failures(project, monkeypatch, successful_checks, failure):
    original = audit.run_uv

    def run_uv(project, arguments, timeout):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("uv", timeout)
        if failure == "missing-tool":
            raise FileNotFoundError("uv is missing")
        if failure == "version" and arguments == ["--version"]:
            return subprocess.CompletedProcess(arguments, 0, "uv 0.1.0 (test)", "")
        if failure == "stale" and arguments[0] == "lock":
            return subprocess.CompletedProcess(arguments, 1, "", "stale lock")
        return original(project, arguments, timeout)

    monkeypatch.setattr(audit, "run_uv", run_uv)
    report = audit.scan(project)
    assert report.status == "failed"
    assert report.errors


def test_changed_input_fails_without_reverting_it(project, monkeypatch, successful_checks):
    original = audit.run_uv

    def run_uv(project, arguments, timeout):
        if arguments[0] == "audit":
            (project / "pyproject.toml").write_text("changed", encoding="utf-8")
        return original(project, arguments, timeout)

    monkeypatch.setattr(audit, "run_uv", run_uv)
    report = audit.scan(project)
    assert report.status == "failed"
    assert any("Read-only invariant violated" in error for error in report.errors)
    assert (project / "pyproject.toml").read_text(encoding="utf-8") == "changed"


@pytest.mark.parametrize("findings,expected_exit", [(False, 0), (True, 1)])
def test_cli_exit_codes_and_report_shape(project, monkeypatch, successful_checks, findings, expected_exit):
    original = audit.run_uv
    monkeypatch.setattr(
        audit,
        "run_uv",
        lambda project, arguments, timeout: (
            subprocess.CompletedProcess(arguments, int(findings), json.dumps(_audit_json(findings=findings)), "")
            if arguments[0] == "audit"
            else original(project, arguments, timeout)
        ),
    )
    output = project / "reports" / "audit.json"
    assert audit.main(["--project", str(project), "--output", str(output)]) == expected_exit
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["feed_url"] == audit.FEED_URL
    assert report["advisory_url"] == audit.ADVISORY_URL
    assert report["audit"]["summary"]["vulnerabilities"] == int(findings)
    assert not report["artifact_downloads_verified"]


@pytest.mark.parametrize("name", ["uv.lock", "pyproject.toml", ".git/config", "dependency_audit.py"])
def test_cli_refuses_to_overwrite_inputs_and_git_metadata(project, monkeypatch, name):
    if name == "dependency_audit.py":
        monkeypatch.setattr(audit, "__file__", str(project / name))
    monkeypatch.setattr(audit, "scan", lambda *args: pytest.fail("Scan must not run"))
    assert audit.main(["--project", str(project), "--output", str(project / name)]) == 2


def test_output_failure_is_explicit(project, monkeypatch, successful_checks, capsys):
    output = project / "report.json"
    output.mkdir()
    assert audit.main(["--project", str(project), "--output", str(output)]) == 2
    assert "Cannot write audit report" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_timeouts_must_be_positive(value):
    with pytest.raises(SystemExit):
        audit.main(["--network-timeout", value])


def test_run_uv_does_not_use_shell_and_enforces_timeout(project, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(audit.subprocess, "run", run)
    audit.run_uv(project, ["audit", "--frozen"], 42)
    assert calls[0][0] == ["uv", "audit", "--frozen"]
    assert calls[0][1]["timeout"] == 42
    assert calls[0][1]["cwd"] == project
    assert not calls[0][1].get("shell", False)


def test_feed_deadline_retains_partial_results_and_terminates_worker(monkeypatch):
    packages = [
        audit.LockedPackage("requests", "2.32.5", audit.FEED_URL),
        audit.LockedPackage("idna", "3.15", audit.FEED_URL),
    ]
    available = audit.FeedCheck("requests", "2.32.5", "available")
    context = Mock()
    results = context.Queue.return_value
    results.get.side_effect = [available, Empty()]
    worker = context.Process.return_value
    worker.pid = 123
    worker.is_alive.side_effect = [True, False]
    monkeypatch.setattr(audit, "get_context", lambda method: context)
    checks = audit.verify_feed(packages, 30, 300)
    assert checks[0] == available
    assert checks[1].status == "failed"
    assert checks[1].error is not None
    assert "deadline" in checks[1].error
    worker.terminate.assert_called_once()
    results.close.assert_called_once()
    assert all(call.kwargs["timeout"] <= 300 for call in results.get.call_args_list)


def test_feed_worker_returns_each_check(monkeypatch):
    package = audit.LockedPackage("requests", "2.32.5", audit.FEED_URL)
    check = audit.FeedCheck(package.name, package.version, "failed", "truncated response")
    monkeypatch.setattr(audit, "check_feed", lambda *args: check)
    results = Mock()
    audit.feed_worker([package], 30, results)
    results.put.assert_called_once_with(check)


def test_feed_timeout_does_not_drop_duplicate_versions_from_different_registries(monkeypatch):
    packages = [
        audit.LockedPackage("requests", "2.32.5", audit.FEED_URL),
        audit.LockedPackage("requests", "2.32.5", "https://pypi.org/simple"),
    ]
    context = Mock()
    results = context.Queue.return_value
    results.get.side_effect = [audit.FeedCheck("requests", "2.32.5", "available"), Empty()]
    worker = context.Process.return_value
    worker.pid = 123
    worker.is_alive.return_value = False
    monkeypatch.setattr(audit, "get_context", lambda method: context)
    checks = audit.verify_feed(packages, 30, 300)
    assert len(checks) == len(packages)
    assert [check.status for check in checks] == ["available", "failed"]


def test_uv_commands_share_one_phase_deadline(project, monkeypatch, successful_checks):
    times = iter([0, 1, 3, 8])
    monkeypatch.setattr(audit.time, "monotonic", lambda: next(times))
    original = audit.run_uv
    timeouts = []

    def run_uv(project, arguments, timeout):
        timeouts.append(timeout)
        return original(project, arguments, timeout)

    monkeypatch.setattr(audit, "run_uv", run_uv)
    report = audit.Report()
    audit.read_lock(project, report)
    audit.audit_lock(project, report, 10)
    assert timeouts == [9, 7, 2]


def test_expired_uv_phase_is_reported(project, monkeypatch, successful_checks):
    times = iter([0, 1, 11])
    monkeypatch.setattr(audit.time, "monotonic", lambda: next(times))
    report = audit.Report()
    audit.read_lock(project, report)
    with pytest.raises(subprocess.TimeoutExpired):
        audit.audit_lock(project, report, 10)
