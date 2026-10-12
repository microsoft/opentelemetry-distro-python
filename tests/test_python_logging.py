# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Regression tests for standard Python logging through the plain provider."""

import logging

import pytest
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from microsoft.opentelemetry._distro import _setup_logging
import microsoft.opentelemetry._distro as distro_module

LOGGER_OPTIONS = [{}, {"logger_name": ""}, {"logger_name": None}, {"logger_name": "root"}]
RESOURCE = Resource({"service.name": "python-logging-regression"})


@pytest.fixture(name="isolated_loggers")
def _isolated_loggers(monkeypatch):
    """Restore handlers and logger settings without touching OTel globals."""
    loggers = {}

    def get_logger(name=""):
        logger = logging.getLogger(name)
        if logger not in loggers:
            loggers[logger] = logger.level
            monkeypatch.setattr(logger, "handlers", [])
            logger.setLevel(logging.WARNING)
            monkeypatch.setattr(logger, "disabled", False)
            monkeypatch.setattr(logger, "propagate", True)
        return logger

    get_logger()
    try:
        yield get_logger
    finally:
        for logger, original_level in loggers.items():
            for handler in logger.handlers:
                handler.close()
            logger.setLevel(original_level)


@pytest.fixture(name="setup_logging")
def _setup_logging_fixture():
    providers = []

    def setup(options):
        provider = _setup_logging(RESOURCE, options)
        assert provider is not None
        providers.append(provider)
        return provider

    yield setup
    for provider in providers:
        provider.shutdown()


@pytest.mark.parametrize("options", LOGGER_OPTIONS)
def test_default_logger_exports_standard_python_logs(options, isolated_loggers, setup_logging):
    exporter = InMemoryLogRecordExporter()
    provider = setup_logging({**options, "log_record_processors": [SimpleLogRecordProcessor(exporter)]})
    logger = isolated_loggers("python_logging.application")

    logger.warning("standard Python log %s", "captured")

    records = exporter.get_finished_logs()
    assert len(records) == 1
    assert records[0].log_record.body == "standard Python log captured"
    assert records[0].resource == RESOURCE
    assert records[0].instrumentation_scope.name == logger.name
    handlers = [handler for handler in isolated_loggers().handlers if isinstance(handler, LoggingHandler)]
    assert len(handlers) == 1
    assert handlers[0]._logger_provider is provider


@pytest.mark.parametrize("options", LOGGER_OPTIONS + [{"logger_name": "python_logging.named"}])
def test_repeated_setup_does_not_duplicate_records(options, isolated_loggers, setup_logging):
    logger = isolated_loggers(options.get("logger_name"))
    existing_handler = logging.NullHandler()
    logger.addHandler(existing_handler)
    exporter = InMemoryLogRecordExporter()
    setup_logging({**options, "log_record_processors": [SimpleLogRecordProcessor(exporter)]})
    original_handlers = list(logger.handlers)

    setup_logging(options)
    logger.warning("one record")

    assert logger.handlers == original_handlers
    assert existing_handler in logger.handlers
    assert len([handler for handler in logger.handlers if isinstance(handler, LoggingHandler)]) == 1
    assert [record.log_record.body for record in exporter.get_finished_logs()] == ["one record"]


def test_explicit_logger_collects_children_and_excludes_other_loggers(isolated_loggers, setup_logging):
    logger = isolated_loggers("python_logging.named")
    child = isolated_loggers("python_logging.named.child")
    unrelated = isolated_loggers("python_logging.unrelated")
    exporter = InMemoryLogRecordExporter()
    setup_logging({"logger_name": logger.name, "log_record_processors": [SimpleLogRecordProcessor(exporter)]})

    logger.warning("named record")
    child.warning("child record")
    unrelated.warning("unrelated record")

    assert [record.log_record.body for record in exporter.get_finished_logs()] == ["named record", "child record"]
    assert not any(isinstance(handler, LoggingHandler) for handler in isolated_loggers().handlers)


@pytest.mark.parametrize("options", [{}, {"logger_name": ""}, {"logger_name": "python_logging.formatted"}])
def test_formatter_is_applied_to_exported_record(options, isolated_loggers, setup_logging):
    logger = isolated_loggers(options.get("logger_name"))
    exporter = InMemoryLogRecordExporter()
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    setup_logging(
        {**options, "logging_formatter": formatter, "log_record_processors": [SimpleLogRecordProcessor(exporter)]}
    )

    logger.warning("formatted %s", "record")

    assert [record.log_record.body for record in exporter.get_finished_logs()] == ["WARNING: formatted record"]


@pytest.mark.parametrize("options", LOGGER_OPTIONS + [{"logger_name": "python_logging.otlp"}])
@pytest.mark.parametrize("disable_logging", [False, True])
def test_plain_otlp_onboarding(options, disable_logging, isolated_loggers, monkeypatch):
    """Exercise the public entry point and real batch processor with a local exporter."""
    from opentelemetry.exporter.otlp.proto.http import _log_exporter

    exporter = InMemoryLogRecordExporter()
    providers = []
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setattr(_log_exporter, "OTLPLogExporter", lambda: exporter)
    monkeypatch.setattr(distro_module, "_initialize_configuration_manager", lambda: None)
    monkeypatch.setattr(distro_module, "_initialize_sdkstats", lambda *args: None)
    monkeypatch.setattr(distro_module, "_setup_instrumentations", lambda *args, **kwargs: None)
    monkeypatch.setattr(distro_module, "set_logger_provider", providers.append)
    logger = isolated_loggers(options.get("logger_name"))

    try:
        distro_module.use_microsoft_opentelemetry(
            **options,
            disable_logging=disable_logging,
            disable_tracing=True,
            disable_metrics=True,
            resource=RESOURCE,
        )
        logger.warning("OTLP application record")
        if disable_logging:
            assert not providers
            assert not any(isinstance(handler, LoggingHandler) for handler in logger.handlers)
            assert not exporter.get_finished_logs()
        else:
            assert len(providers) == 1
            assert providers[0].force_flush()
            assert [record.log_record.body for record in exporter.get_finished_logs()] == ["OTLP application record"]
    finally:
        for provider in providers:
            provider.shutdown()
