# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Span and log-record processors that propagate
``microsoft.gen_ai.main_agent.*`` attributes from the top-level
(user-facing) GenAI agent so that all downstream telemetry is attributed
to the main agent rather than internal sub-agents in a multi-agent system.
"""

from microsoft.opentelemetry._constants import (
    GEN_AI_MAIN_AGENT_ATTRIBUTE_PREFIX,
    GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY,
    GEN_AI_MAIN_AGENT_ID_KEY,
    GEN_AI_MAIN_AGENT_NAME_KEY,
    GEN_AI_MAIN_AGENT_VERSION_KEY,
)
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)
from opentelemetry import context as context_api
from opentelemetry import trace
from opentelemetry.sdk._logs import LogRecordProcessor, ReadWriteLogRecord
from opentelemetry.sdk.trace import ReadableSpan, Span
from opentelemetry.sdk.trace.export import SpanProcessor
from opentelemetry.trace import Span as SpanAPI
from opentelemetry.util.types import AttributeValue

# Each row: (target attribute on current span,
#            primary source attribute on parent span,
#            fallback source attribute on parent span)
_PROPAGATION_TABLE: tuple[tuple[str, str, str], ...] = (
    (GEN_AI_MAIN_AGENT_NAME_KEY, GEN_AI_MAIN_AGENT_NAME_KEY, GEN_AI_AGENT_NAME_KEY),
    (GEN_AI_MAIN_AGENT_ID_KEY, GEN_AI_MAIN_AGENT_ID_KEY, GEN_AI_AGENT_ID_KEY),
    (GEN_AI_MAIN_AGENT_VERSION_KEY, GEN_AI_MAIN_AGENT_VERSION_KEY, GEN_AI_AGENT_VERSION_KEY),
    (
        GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY,
        GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY,
        GEN_AI_CONVERSATION_ID_KEY,
    ),
)

# Used at on_end to copy the current span's own gen_ai.* attributes onto the
# microsoft.gen_ai.main_agent.* attributes when the span is the top-level
# invoke_agent span and no main_agent.* attribute has been propagated yet.
_SELF_COPY_TABLE: tuple[tuple[str, str], ...] = tuple(
    (target, fallback) for target, _primary, fallback in _PROPAGATION_TABLE
)


class GenAIMainAgentSpanProcessor(SpanProcessor):
    """Propagates ``microsoft.gen_ai.main_agent.*`` attributes onto spans.

    On ``on_start``: copies main-agent attributes from the parent span (or
    falls back to the parent's ``gen_ai.agent.*`` / ``gen_ai.conversation.id``
    attributes) onto the new span.  Also stores a reference to the parent
    ``Span`` so that ``on_end`` can retry propagation for children whose
    parent attributes were not yet available at ``on_start`` time.

    On ``on_end``: when the span is itself an ``invoke_agent`` operation and
    has not already been enriched, copies its own ``gen_ai.agent.*`` /
    ``gen_ai.conversation.id`` attributes onto ``microsoft.gen_ai.main_agent.*``
    so the top-level agent identifies itself as the main agent.  For other
    spans that still lack ``microsoft.gen_ai.main_agent.*`` attributes, a
    fallback read from the (now potentially enriched) parent is attempted.
    """

    def __init__(self) -> None:
        # span-id → parent Span, used for on_end fallback propagation
        self._parent_spans: dict[int, SpanAPI] = {}

    def on_start(self, span: Span, parent_context: context_api.Context | None = None) -> None:
        parent = trace.get_current_span(parent_context)
        if not parent.get_span_context().is_valid:
            return

        # Store parent reference for on_end fallback when on_start misses
        # attributes that are set on the parent after this child is created.
        span_ctx = span.get_span_context()
        if span_ctx.is_valid:
            self._parent_spans[span_ctx.span_id] = parent

        parent_attributes = getattr(parent, "attributes", None) or {}
        for target, primary, fallback in _PROPAGATION_TABLE:
            value = parent_attributes.get(primary)
            if value is None:
                value = parent_attributes.get(fallback)
            if value is not None:
                span.set_attribute(target, value)

    def on_end(self, span: ReadableSpan) -> None:
        span_id = span.context.span_id
        parent = self._parent_spans.pop(span_id, None)

        attributes = span.attributes or {}

        # Already enriched — nothing to do.
        if any(k.startswith(GEN_AI_MAIN_AGENT_ATTRIBUTE_PREFIX) for k in attributes):
            return

        # Access the internal mutable attributes dict.  ``on_end`` receives a
        # ``ReadableSpan`` which lacks ``set_attribute``, so we write to the
        # underlying ``BoundedAttributes`` mapping directly.
        mutable = getattr(span, "_attributes", None)
        if mutable is None:
            return

        # Build the attributes to write before touching the (now frozen) span.
        updates: dict[str, AttributeValue] = {}

        # Self-promotion: top-level invoke_agent spans copy their own
        # gen_ai.agent.* → microsoft.gen_ai.main_agent.*
        if attributes.get(GEN_AI_OPERATION_NAME_KEY) == INVOKE_AGENT_OPERATION_NAME:
            for target, source in _SELF_COPY_TABLE:
                value = attributes.get(source)
                if value is not None:
                    updates[target] = value
        # Fallback propagation: re-read from the parent span whose attributes
        # may have been set after this child was created (timing issue).
        if parent is not None:
            parent_attributes = getattr(parent, "attributes", None) or {}
            for target, primary, fallback in _PROPAGATION_TABLE:
                value = parent_attributes.get(primary)
                if value is None:
                    value = parent_attributes.get(fallback)
                if value is not None:
                    updates[target] = value

        if not updates:
            return

        # OTel SDK >= 1.43 freezes span attributes (``_immutable = True``) inside
        # ``end()`` *before* invoking ``on_end``.  Writing then raises ``TypeError``.
        # Temporarily lift the freeze for our own synchronous writes and always
        # restore it so the exported ``ReadableSpan`` snapshot stays frozen.
        was_immutable = getattr(mutable, "_immutable", False)
        if was_immutable:
            mutable._immutable = False  # pylint: disable=protected-access
            try:
                for target, value in updates.items():
                    mutable[target] = value
            finally:
                mutable._immutable = True  # pylint: disable=protected-access
        else:
            for target, value in updates.items():
                mutable[target] = value

    def shutdown(self) -> None:
        self._parent_spans.clear()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class GenAIMainAgentLogRecordProcessor(LogRecordProcessor):
    """Copies any ``microsoft.gen_ai.main_agent.*`` attributes from the
    current span onto every emitted log record.
    """

    def on_emit(self, log_record: ReadWriteLogRecord) -> None:
        span = trace.get_current_span()
        if not span.get_span_context().is_valid:
            return

        span_attributes = getattr(span, "attributes", None) or {}
        main_agent_attributes = {
            key: value for key, value in span_attributes.items() if key.startswith(GEN_AI_MAIN_AGENT_ATTRIBUTE_PREFIX)
        }
        if not main_agent_attributes:
            return

        if log_record.log_record.attributes is None:
            log_record.log_record.attributes = {}
        for key, value in main_agent_attributes.items():
            log_record.log_record.attributes[key] = value  # type: ignore[index]

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
