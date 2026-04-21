# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from microsoft_agents_a365.observability.core.exporters.enriching_span_processor import (
    register_span_enricher,
    unregister_span_enricher,
)
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.trace import get_tracer_provider

from microsoft.opentelemetry._agent_framework._span_enricher import enrich_agent_framework_span
from microsoft.opentelemetry._agent_framework._span_processor import AgentFrameworkSpanProcessor

_instruments = ("agent-framework >= 1.0.0",)


class AgentFrameworkInstrumentor(BaseInstrumentor):
    """Instruments Agent Framework with Agent365 observability."""

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs: Any) -> None:
        provider = get_tracer_provider()

        self._processor = AgentFrameworkSpanProcessor()
        provider.add_span_processor(self._processor)

        register_span_enricher(enrich_agent_framework_span)

    def _uninstrument(self, **kwargs: Any) -> None:
        unregister_span_enricher()

        if hasattr(self, "_processor"):
            self._processor.shutdown()
