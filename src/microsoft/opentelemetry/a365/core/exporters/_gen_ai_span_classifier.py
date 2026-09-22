# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Classify spans for Agent365 GenAI baggage propagation."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_INITIAL_SPAN_NAMES,
    GEN_AI_INSTRUMENTATION_SCOPE_ROOTS,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_PROCESSOR_OPERATION_NAMES,
)


@dataclass(frozen=True)
class _GenAISpanClassification:
    """Whether a span is GenAI and, when identifiable, the operation it represents."""

    is_gen_ai_span: bool
    operation_name: str | None = None


def _recognized_operation_name(value: object | None) -> str | None:
    return value if isinstance(value, str) and value in GEN_AI_PROCESSOR_OPERATION_NAMES else None


def _span_name(span: Any) -> str | None:
    span_name = getattr(span, "name", None)
    return span_name if isinstance(span_name, str) else None


def _operation_name_from_span_name(span: Any) -> str | None:
    span_name = _span_name(span)
    if span_name is None:
        return None

    for operation_name in GEN_AI_PROCESSOR_OPERATION_NAMES:
        if span_name == operation_name or span_name.startswith(f"{operation_name} "):
            return operation_name
    return None


def _has_known_initial_span_name(span: Any) -> bool:
    """Match span names supported instrumentations use before renaming the span."""
    span_name = _span_name(span)
    if span_name is None:
        return False

    return any(span_name == known or span_name.startswith(f"{known} ") for known in GEN_AI_INITIAL_SPAN_NAMES)


def _instrumentation_scope_name(span: Any) -> str | None:
    """Read the tracer (source) name recorded on a ReadWriteSpan."""
    # pylint: disable=broad-exception-caught
    for attribute_name in ("instrumentation_scope", "instrumentation_info"):
        try:
            scope = getattr(span, attribute_name, None)
            scope_name = getattr(scope, "name", None) if scope is not None else None
        except Exception:
            continue
        if isinstance(scope_name, str) and scope_name:
            return scope_name
    return None


def _is_supported_gen_ai_scope(span: Any) -> bool:
    scope_name = _instrumentation_scope_name(span)
    if scope_name is None:
        return False

    return any(scope_name == root or scope_name.startswith(f"{root}.") for root in GEN_AI_INSTRUMENTATION_SCOPE_ROOTS)


def _classify_gen_ai_span(
    span: Any,
    existing_attributes: Mapping[str, object],
    baggage_map: Mapping[str, object],
) -> _GenAISpanClassification:
    """Resolve whether a span is GenAI and which operation it represents.

    An explicit ``gen_ai.operation.name`` attribute is authoritative over the
    baggage and span-name inference signals, including when it holds a value
    this processor does not model (``chain``, ``embeddings``,
    ``text_completion``, ``generate_content``, ``create_agent``). Such a span is
    still GenAI when a supported instrumentation emitted it, but its operation
    stays unknown so invoke_agent-only attributes are withheld.

    Without an explicit operation attribute, a recognized span-name operation
    takes precedence over inherited operation baggage.
    """
    if GEN_AI_OPERATION_NAME_KEY in existing_attributes:
        explicit_operation_name = _recognized_operation_name(existing_attributes.get(GEN_AI_OPERATION_NAME_KEY))
        if explicit_operation_name is not None:
            return _GenAISpanClassification(True, explicit_operation_name)
        return _GenAISpanClassification(_is_supported_gen_ai_scope(span))

    operation_name = _operation_name_from_span_name(span)
    if operation_name is None:
        operation_name = _recognized_operation_name(baggage_map.get(GEN_AI_OPERATION_NAME_KEY))
    if operation_name is not None:
        return _GenAISpanClassification(True, operation_name)

    return _GenAISpanClassification(_has_known_initial_span_name(span) or _is_supported_gen_ai_scope(span))
