# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
"""Performance benchmarks for the Microsoft OpenTelemetry distro.

These tests are skipped by default — they only execute when pytest is invoked
with ``--benchmark-only`` (or any other ``--benchmark-*`` flag) by the
performance CI workflow.

Two pairs of scenarios are measured:

* ``azure_monitor_span`` / ``azure_monitor_log`` (gating): the per-operation
  cost the distro adds on top of upstream OpenTelemetry.
* ``otel_span`` / ``otel_log`` (informational): a plain upstream
  ``opentelemetry-sdk`` reference. They are reported but never fail the
  build.
"""

# pylint: disable=redefined-outer-name
# (pytest fixtures shadow the fixture function name by design.)

from __future__ import annotations

import logging

import pytest

_FAKE_CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
    "IngestionEndpoint=https://localhost/;"
    "LiveEndpoint=https://localhost/"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _azure_monitor_configured() -> None:
    """Call ``configure_azure_monitor`` once per pytest session with all
    network-facing features disabled so the benchmark measures only the
    in-process hot path."""
    from microsoft.opentelemetry._azure_monitor._configure import configure_azure_monitor

    configure_azure_monitor(
        connection_string=_FAKE_CONNECTION_STRING,
        disable_metrics=True,
        enable_live_metrics=False,
        enable_performance_counters=False,
        disable_offline_storage=True,
    )


@pytest.fixture
def azure_monitor_tracer(_azure_monitor_configured):
    from opentelemetry import trace

    return trace.get_tracer("perf.azure_monitor_span")


@pytest.fixture
def azure_monitor_logger(_azure_monitor_configured):
    logger = logging.getLogger("perf.azure_monitor_log")
    logger.setLevel(logging.INFO)
    return logger


@pytest.fixture
def otel_tracer():
    # Build our own provider rather than touching the global TracerProvider so
    # this reference benchmark is insulated from `configure_azure_monitor`
    # being called by other tests in the same session.
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(InMemorySpanExporter()))
    return provider.get_tracer("perf.otel_span")


@pytest.fixture
def otel_logger():
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, InMemoryLogExporter

    provider = LoggerProvider()
    provider.add_log_record_processor(BatchLogRecordProcessor(InMemoryLogExporter()))
    handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    logger = logging.getLogger("perf.otel_log")
    logger.setLevel(logging.INFO)
    if not any(isinstance(h, LoggingHandler) for h in logger.handlers):
        logger.addHandler(handler)
    return logger


def _mark_gating(benchmark, gating: bool) -> None:
    benchmark.extra_info["gating"] = gating


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="span")
def test_azure_monitor_span(benchmark, azure_monitor_tracer):
    _mark_gating(benchmark, True)
    tracer = azure_monitor_tracer

    def _op() -> None:
        with tracer.start_as_current_span("bench") as span:
            span.set_attribute("bench.attr", 1)

    benchmark(_op)


@pytest.mark.benchmark(group="log")
def test_azure_monitor_log(benchmark, azure_monitor_logger):
    _mark_gating(benchmark, True)
    logger = azure_monitor_logger

    def _op() -> None:
        logger.info("bench message %s", 1)

    benchmark(_op)


@pytest.mark.benchmark(group="span")
def test_otel_span(benchmark, otel_tracer):
    _mark_gating(benchmark, False)
    tracer = otel_tracer

    def _op() -> None:
        with tracer.start_as_current_span("bench") as span:
            span.set_attribute("bench.attr", 1)

    benchmark(_op)


@pytest.mark.benchmark(group="log")
def test_otel_log(benchmark, otel_logger):
    _mark_gating(benchmark, False)
    logger = otel_logger

    def _op() -> None:
        logger.info("bench message %s", 1)

    benchmark(_op)
