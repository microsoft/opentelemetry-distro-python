# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from azure.core.pipeline.transport import HttpRequest, HttpResponse, HttpTransport
from azure.core.credentials import AccessToken
from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry import use_microsoft_opentelemetry

requires_routing = pytest.mark.skipif(
    find_spec("azure.monitor.opentelemetry.exporter._routing") is None,
    reason="Requires an exporter build with multi-endpoint routing support",
)

HOST_KEY = "1234abcd-5678-4efa-8abc-1234567890ab"


class _Response(HttpResponse):
    def __init__(self, request):
        super().__init__(request, None)
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self.content_type = "application/json"
        count = len(json.loads(request.body))
        self._body = json.dumps({"itemsReceived": count, "itemsAccepted": count, "errors": []}).encode()

    def body(self):
        return self._body

    def stream_download(self, pipeline, **kwargs):
        return iter([self._body])

    def json(self):
        return json.loads(self._body)


def test_response_stream_download():
    request = HttpRequest("POST", "https://host.example/v2.1/track")
    request.set_json_body([{}])
    response = _Response(request)

    assert list(response.stream_download(MagicMock())) == [response.body()]


@pytest.fixture(name="routing_transport")
def _routing_transport(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("OTEL_") or name in (
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "APPINSIGHTS_INSTRUMENTATIONKEY",
            "APPLICATIONINSIGHTS_EXPERIMENTAL_FEATURES",
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OTEL_EXPERIMENTAL_RESOURCE_DETECTORS", "")
    monkeypatch.setattr("azure.monitor.opentelemetry.exporter.export._base._enabled_experimental_features", None)
    for name in (
        "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL",
        "APPLICATIONINSIGHTS_SDKSTATS_DISABLED",
        "APPLICATIONINSIGHTS_CONTROLPLANE_DISABLED",
        "APPLICATIONINSIGHTS_OPENTELEMETRY_RESOURCE_METRIC_DISABLED",
    ):
        monkeypatch.setenv(name, "true")

    def unexpected_network(*args, **kwargs):
        pytest.fail("Routing tests must not perform external network calls")

    monkeypatch.setattr(socket, "create_connection", unexpected_network)
    monkeypatch.setattr("requests.sessions.Session.request", unexpected_network)
    transport = MagicMock(spec=HttpTransport)
    transport.close.return_value = None
    transport.__exit__.side_effect = lambda *args: transport.close()
    transport.send.side_effect = lambda request, **kwargs: _Response(request)
    return transport


@requires_routing
@pytest.mark.parametrize(
    "features,with_host,routing",
    [
        ("multi_endpoint_routing", True, True),
        ("multi_endpoint_routing", False, True),
        (" GEN_AI_INPUT_OUTPUT_LIMIT_INCREASE, MULTI_ENDPOINT_ROUTING, ,multi_endpoint_routing ", True, True),
        ("gen_ai_input_output_limit_increase", True, False),
        ("multi_endpoint_routing_extra", True, False),
        ("", True, False),
        (None, True, False),
    ],
    ids=["with-host", "without-host", "multiple-features", "other-feature", "wrong-name", "empty", "unset"],
)
def test_distro_routes_all_signals(
    features, with_host, routing, routing_transport, isolated_loggers, tmp_path, monkeypatch
):
    logger = isolated_loggers("routing-end-to-end")
    credential = MagicMock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("test-token", int(time.time()) + 3600)
    options = {}
    if features is not None:
        monkeypatch.setenv("APPLICATIONINSIGHTS_EXPERIMENTAL_FEATURES", features)
    if with_host:
        options["azure_monitor_connection_string"] = (
            f"InstrumentationKey={HOST_KEY};IngestionEndpoint=https://host.example/"
        )

    with ExitStack() as stack:
        for name in ("_setup_instrumentations", "_initialize_sdkstats"):
            stack.enter_context(patch(f"microsoft.opentelemetry._distro.{name}"))
        registrations = [
            stack.enter_context(patch(f"microsoft.opentelemetry._distro.set_{name}_provider"))
            for name in ("tracer", "meter", "logger")
        ]
        use_microsoft_opentelemetry(
            enable_azure_monitor=True,
            azure_monitor_enable_live_metrics=False,
            azure_monitor_enable_performance_counters=False,
            azure_monitor_exporter_credential=credential,
            azure_monitor_exporter_disable_offline_storage=True,
            azure_monitor_exporter_storage_directory=str(tmp_path),
            azure_monitor_browser_sdk_loader_config={"enabled": False},
            instrumentation_options={"azure_sdk": {"enabled": False}},
            sampling_ratio=1.0,
            resource=Resource({"service.name": "routing-service", "service.instance.id": "routing-instance"}),
            logger_name=logger.name,
            transport=routing_transport,
            **options,
        )
        providers = [registration.call_args.args[0] for registration in registrations]
        for provider in providers:
            stack.callback(provider.shutdown)
        tracer_provider, meter_provider, _ = providers
        tracer = tracer_provider.get_tracer(__name__)
        counter = meter_provider.get_meter(__name__).create_counter("routing.counter")
        for key, endpoint, auth in (
            ("key-one", "https://one.example/", "ikey"),
            ("key-two", "https://two.example/", "aad"),
        ):
            attributes = {
                "microsoft.instrumentation_key": key,
                "microsoft.ingestion_endpoint": endpoint,
                "microsoft.ingestion_auth": auth,
            }
            with tracer.start_as_current_span(f"operation-{key}", attributes=attributes) as span:
                span.add_event("routed-event")
            logger.warning("routed-log", extra=attributes)
            counter.add(1, attributes)
        if routing:
            with tracer.start_as_current_span("unrouted"):
                pass
            logger.warning("unrouted")
            counter.add(100)
        for provider in providers:
            assert provider.force_flush()

    destinations = {}
    for call in routing_transport.send.call_args_list:
        request = call.args[0]
        if routing:
            assert request.headers.get("Authorization") == (
                "Bearer test-token" if request.url.startswith("https://two.example/") else None
            )
        for item in json.loads(request.body):
            destinations.setdefault((request.url, item["iKey"]), []).append(item)
    expected = (
        {("https://one.example/v2.1/track", "key-one"), ("https://two.example/v2.1/track", "key-two")}
        if routing
        else {("https://host.example//v2.1/track", HOST_KEY)}
    )
    assert set(destinations) == expected
    for items in destinations.values():
        assert {item["data"]["baseType"] for item in items} == {"RemoteDependencyData", "MessageData", "MetricData"}
        assert sum(item["data"]["baseType"] == "RemoteDependencyData" for item in items) == (1 if routing else 2)
        if routing:
            assert len(items) == 4
            assert {
                item["data"]["baseData"]["message"] for item in items if item["data"]["baseType"] == "MessageData"
            } == {"routed-event", "routed-log"}
            metric = next(item for item in items if item["data"]["baseType"] == "MetricData")
            assert metric["data"]["baseData"]["metrics"][0]["value"] == 1
        for item in items:
            assert item["tags"]["ai.cloud.role"] == "routing-service"
            assert item["tags"]["ai.cloud.roleInstance"] == "routing-instance"
            if routing:
                properties = item["data"]["baseData"]["properties"]
                assert "microsoft.instrumentation_key" not in properties
                assert "microsoft.ingestion_endpoint" not in properties
                assert "microsoft.ingestion_auth" not in properties


def _run_demo(script_name, tmp_path):
    pytest.importorskip("cryptography", reason="Install the local routing demo requirements to test verified HTTPS")
    script = Path(__file__).resolve().parents[2] / "samples" / "distro" / "multi_endpoint_routing" / script_name
    result = subprocess.run(
        [sys.executable, str(script), "--output", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@requires_routing
def test_offline_storage_survives_process_restart(tmp_path):
    output = _run_demo("restart_demo.py", tmp_path)
    assert "PASS: process restart, durable storage, route reopening, exact replay, and disk cleanup." in output
    runs = list(tmp_path.glob("restart-*"))
    assert len(runs) == 1
    written = json.loads((runs[0] / "process-write.json").read_text(encoding="utf-8"))
    reopened = json.loads((runs[0] / "process-reopen.json").read_text(encoding="utf-8"))
    assert written["pid"] != reopened["pid"]
    assert written["pending_blobs"] > 0
    assert reopened["pending_blobs"] == 0


@requires_routing
@pytest.mark.parametrize(
    "script_name,expected",
    [
        (
            "crash_demo.py",
            "PASS: abrupt mid-write exit, committed-data recovery, partial-batch isolation, and stale-file cleanup.",
        ),
        (
            "repeated_failure_demo.py",
            "PASS: repeated replay failures, renewed backoff, preserved payloads, and eventual recovery.",
        ),
    ],
)
def test_offline_storage_fault_recovery(script_name, expected, tmp_path):
    output = _run_demo(script_name, tmp_path)
    assert expected in output
