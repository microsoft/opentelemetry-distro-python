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

from microsoft.opentelemetry._semantic_kernel._span_enricher import enrich_semantic_kernel_span
from microsoft.opentelemetry._semantic_kernel._span_processor import SemanticKernelSpanProcessor

_instruments = ("semantic-kernel >= 1.0.0",)


class SemanticKernelInstrumentor(BaseInstrumentor):
    """Instruments Semantic Kernel with Agent365 observability."""

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs: Any) -> None:
        provider = get_tracer_provider()

        self._processor = SemanticKernelSpanProcessor()
        provider.add_span_processor(self._processor)

        register_span_enricher(enrich_semantic_kernel_span)

    def _uninstrument(self, **kwargs: Any) -> None:
        unregister_span_enricher()

        if hasattr(self, "_processor"):
            self._processor.shutdown()
