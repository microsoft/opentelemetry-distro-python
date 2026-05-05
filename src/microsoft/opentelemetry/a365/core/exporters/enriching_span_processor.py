# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Span enrichment support for the Agent365 exporter pipeline.

Vendored from microsoft-agents-a365-observability-core exporters/enriching_span_processor.py.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Optional

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from microsoft.opentelemetry.a365.constants import (
    FOUNDRY_AGENT_IDENTITY_ENV,
    FOUNDRY_HOSTING_ENVIRONMENT_ENV,
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)
from microsoft.opentelemetry.a365.core.exporters.enriched_span import EnrichedReadableSpan

logger = logging.getLogger(__name__)

# Single span enricher - only one platform instrumentor should be active at a time
_span_enricher: Optional[Callable[[ReadableSpan], ReadableSpan]] = None
_enricher_lock = threading.Lock()


# pylint: disable=global-statement, broad-exception-caught
def register_span_enricher(enricher: Callable[[ReadableSpan], ReadableSpan]) -> None:
    """Register the span enricher for the active platform instrumentor.

    Only one enricher can be registered at a time since auto-instrumentation
    is platform-specific (Semantic Kernel, LangChain, or OpenAI Agents).

    Raises RuntimeError if an enricher is already registered.
    """
    global _span_enricher  # noqa: PLW0603
    with _enricher_lock:
        if _span_enricher is not None:
            raise RuntimeError(
                "A span enricher is already registered. Only one platform instrumentor can be active at a time."
            )
        _span_enricher = enricher
        logger.debug("Span enricher registered: %s", enricher.__name__)


def unregister_span_enricher() -> None:
    """Unregister the current span enricher."""
    global _span_enricher  # noqa: PLW0603
    with _enricher_lock:
        if _span_enricher is not None:
            logger.debug("Span enricher unregistered: %s", _span_enricher.__name__)
            _span_enricher = None


def get_span_enricher() -> Optional[Callable[[ReadableSpan], ReadableSpan]]:
    """Get the currently registered span enricher."""
    with _enricher_lock:
        return _span_enricher


class _EnrichingBatchSpanProcessor(BatchSpanProcessor):
    """BatchSpanProcessor that applies the registered enricher before batching."""

    def __init__(
        self,
        *args: object,
        suppress_invoke_agent_input: bool = False,
        **kwargs: object,
    ):
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._suppress_invoke_agent_input = suppress_invoke_agent_input

        # Foundry-hosted agent ID override: only active when running in
        # Foundry hosting environment and identity env var is set.
        foundry_env = os.environ.get(FOUNDRY_HOSTING_ENVIRONMENT_ENV, "").strip()
        agent_identity = os.environ.get(FOUNDRY_AGENT_IDENTITY_ENV, "").strip()
        if foundry_env == "1" and agent_identity:
            self._foundry_agent_id: Optional[str] = agent_identity
        else:
            self._foundry_agent_id = None

    def on_end(self, span: ReadableSpan) -> None:
        """Apply the span enricher and pass to parent for batching."""
        enriched_span = span

        enricher = get_span_enricher()
        if enricher is not None:
            try:
                enriched_span = enricher(span)
            except Exception:
                logger.exception(
                    "Span enricher %s raised an exception, using original span",
                    enricher.__name__,
                )

        # Apply input message suppression for InvokeAgent spans
        if self._suppress_invoke_agent_input:
            attrs = enriched_span.attributes or {}
            operation_name = attrs.get(GEN_AI_OPERATION_NAME_KEY)
            if (
                enriched_span.name.startswith(INVOKE_AGENT_OPERATION_NAME)
                and operation_name == INVOKE_AGENT_OPERATION_NAME
            ):
                enriched_span = EnrichedReadableSpan(
                    enriched_span,
                    extra_attributes={},
                    excluded_attribute_keys={GEN_AI_INPUT_MESSAGES_KEY},
                )

        # Override gen_ai.agent.id when running in Foundry-hosted environment
        if self._foundry_agent_id is not None:
            enriched_span = EnrichedReadableSpan(
                enriched_span,
                extra_attributes={GEN_AI_AGENT_ID_KEY: self._foundry_agent_id},
            )

        super().on_end(enriched_span)
