# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Span processor for propagating OpenTelemetry baggage entries onto spans.

For every new span:
  * Retrieve the current (or parent) context
  * Obtain all baggage entries
  * For each documented key with a truthy value not already present as a span
    attribute, add it via span.set_attribute
  * Never overwrites existing attributes

Custom baggage is propagated only to recognized GenAI spans. A span is
recognized as GenAI when any of the following signals fires at ``on_start``:

  1. An explicit ``gen_ai.operation.name`` attribute holding a recognized
     operation. An explicit *unrecognized* value is authoritative and
     suppresses the two inference signals below.
  2. A recognized ``gen_ai.operation.name`` baggage entry.
  3. A span name that is (or starts with) a recognized operation name.
  4. A span name a supported instrumentation is known to use before it renames
     the span (Semantic Kernel ``chat.completions <model>``).
  5. The instrumentation scope (source) name of a supported GenAI
     instrumentation.

Only signals 1-3 identify *which* operation a span represents, which is what
gates the invoke_agent-only attributes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from opentelemetry import baggage, context
from opentelemetry.sdk.trace import SpanProcessor as BaseSpanProcessor

from microsoft.opentelemetry.a365.core.constants import (
    CHANNEL_LINK_KEY,
    CHANNEL_NAME_KEY,
    CUSTOM_KEYS_BAGGAGE_KEY,
    CUSTOM_PARENT_SPAN_ID_KEY,
    CUSTOM_SPAN_NAME_KEY,
    GEN_AI_AGENT_AUID_KEY,
    GEN_AI_AGENT_BLUEPRINT_ID_KEY,
    GEN_AI_AGENT_DESCRIPTION_KEY,
    GEN_AI_AGENT_EMAIL_KEY,
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_PLATFORM_ID_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_CALLER_AGENT_APPLICATION_ID_KEY,
    GEN_AI_CALLER_AGENT_EMAIL_KEY,
    GEN_AI_CALLER_AGENT_ID_KEY,
    GEN_AI_CALLER_AGENT_NAME_KEY,
    GEN_AI_CALLER_AGENT_PLATFORM_ID_KEY,
    GEN_AI_CALLER_AGENT_USER_ID_KEY,
    GEN_AI_CALLER_AGENT_VERSION_KEY,
    GEN_AI_CALLER_CLIENT_IP_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_CONVERSATION_ITEM_LINK_KEY,
    GEN_AI_INITIAL_SPAN_NAMES,
    GEN_AI_INSTRUMENTATION_SCOPE_ROOTS,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_PROCESSOR_OPERATION_NAMES,
    INVOKE_AGENT_OPERATION_NAME,
    SERVER_ADDRESS_KEY,
    SERVER_PORT_KEY,
    SERVICE_NAME_KEY,
    SESSION_DESCRIPTION_KEY,
    SESSION_ID_KEY,
    TENANT_ID_KEY,
    USER_EMAIL_KEY,
    USER_ID_KEY,
    USER_NAME_KEY,
)

# mypy: disable-error-code="no-untyped-def"

# Generic / common tracing attributes propagated from baggage to all spans
COMMON_ATTRIBUTES = [
    TENANT_ID_KEY,
    CUSTOM_PARENT_SPAN_ID_KEY,
    CUSTOM_SPAN_NAME_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_CONVERSATION_ITEM_LINK_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_DESCRIPTION_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_AGENT_EMAIL_KEY,
    GEN_AI_AGENT_BLUEPRINT_ID_KEY,
    GEN_AI_AGENT_AUID_KEY,
    GEN_AI_AGENT_PLATFORM_ID_KEY,
    SESSION_ID_KEY,
    SESSION_DESCRIPTION_KEY,
    GEN_AI_CALLER_CLIENT_IP_KEY,
    CHANNEL_NAME_KEY,
    CHANNEL_LINK_KEY,
    USER_ID_KEY,
    USER_NAME_KEY,
    USER_EMAIL_KEY,
    SERVICE_NAME_KEY,
]

# Invoke Agent-specific attributes (only propagated to invoke_agent spans)
INVOKE_AGENT_ATTRIBUTES = [
    GEN_AI_CALLER_AGENT_ID_KEY,
    GEN_AI_CALLER_AGENT_NAME_KEY,
    GEN_AI_CALLER_AGENT_USER_ID_KEY,
    GEN_AI_CALLER_AGENT_EMAIL_KEY,
    GEN_AI_CALLER_AGENT_APPLICATION_ID_KEY,
    GEN_AI_CALLER_AGENT_PLATFORM_ID_KEY,
    GEN_AI_CALLER_AGENT_VERSION_KEY,
    SERVER_ADDRESS_KEY,
    SERVER_PORT_KEY,
]


@dataclass(frozen=True)
class _GenAISpanClassification:
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


def _classify_gen_ai_operation(
    span: Any,
    existing_attributes: Mapping[str, object],
    baggage_map: Mapping[str, object],
) -> str | None:
    """Resolve the GenAI operation a span represents, or ``None`` if unknown."""
    if GEN_AI_OPERATION_NAME_KEY in existing_attributes:
        return _recognized_operation_name(existing_attributes.get(GEN_AI_OPERATION_NAME_KEY))

    baggage_operation_name = _recognized_operation_name(baggage_map.get(GEN_AI_OPERATION_NAME_KEY))
    if baggage_operation_name is not None:
        return baggage_operation_name

    return _operation_name_from_span_name(span)


def _classify_gen_ai_span(
    span: Any,
    existing_attributes: Mapping[str, object],
    baggage_map: Mapping[str, object],
) -> _GenAISpanClassification:
    operation_name = _classify_gen_ai_operation(span, existing_attributes, baggage_map)
    if operation_name is not None:
        return _GenAISpanClassification(True, operation_name)

    if GEN_AI_OPERATION_NAME_KEY in existing_attributes:
        # The span declared an operation this processor does not handle.
        return _GenAISpanClassification(False)

    return _GenAISpanClassification(_has_known_initial_span_name(span) or _is_supported_gen_ai_scope(span))


def _is_gen_ai_span(span: Any, existing_attributes: Mapping[str, object], baggage_map: Mapping[str, object]) -> bool:
    return _classify_gen_ai_span(span, existing_attributes, baggage_map).is_gen_ai_span


def _custom_baggage_keys(baggage_map) -> list[str]:
    metadata = baggage_map.get(CUSTOM_KEYS_BAGGAGE_KEY)
    if not metadata:
        return []

    keys: list[str] = []
    for raw_key in str(metadata).split(","):
        key = raw_key.strip()
        if not key or key == CUSTOM_KEYS_BAGGAGE_KEY:
            continue
        if key not in keys:
            keys.append(key)
    return keys


# pylint: disable=broad-exception-caught, too-many-branches, useless-parent-delegation
# pylint: disable=global-statement
class A365SpanProcessor(BaseSpanProcessor):
    """Span processor that stamps agent identity and propagates baggage to span attributes.

    Static identity (tenant_id, agent_id) is set from configuration on every span.
    Additional baggage entries are propagated selectively for documented keys.
    Never overwrites existing attributes.
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        agent_id: str | None = None,
    ):
        super().__init__()
        self._tenant_id = tenant_id
        self._agent_id = agent_id

    def on_start(self, span, parent_context=None):  # type: ignore[override]
        ctx = parent_context or context.get_current()

        # Stamp static identity from configuration (never overwrite existing)
        try:
            existing = getattr(span, "attributes", {}) or {}
        except Exception:
            existing = {}

        if self._tenant_id and TENANT_ID_KEY not in existing:
            try:
                span.set_attribute(TENANT_ID_KEY, self._tenant_id)
            except Exception:
                pass
        if self._agent_id and GEN_AI_AGENT_ID_KEY not in existing:
            try:
                span.set_attribute(GEN_AI_AGENT_ID_KEY, self._agent_id)
            except Exception:
                pass

        # Refresh existing after stamping identity
        try:
            existing = getattr(span, "attributes", {}) or {}
        except Exception:
            existing = {}

        if ctx is None:
            return super().on_start(span, parent_context)

        try:
            baggage_map = baggage.get_all(ctx) or {}
        except Exception:
            baggage_map = {}

        classification = _classify_gen_ai_span(span, existing, baggage_map)

        target_keys = list(COMMON_ATTRIBUTES)
        if classification.operation_name == INVOKE_AGENT_OPERATION_NAME:
            for k in INVOKE_AGENT_ATTRIBUTES:
                if k not in target_keys:
                    target_keys.append(k)
        if classification.is_gen_ai_span:
            for k in _custom_baggage_keys(baggage_map):
                if k not in target_keys:
                    target_keys.append(k)

        for key in target_keys:
            if key in existing:
                continue
            value = baggage_map.get(key)
            if not value:
                continue
            try:
                span.set_attribute(key, value)
            except Exception:
                continue

        return super().on_start(span, parent_context)

    def on_end(self, span):  # type: ignore[override]
        super().on_end(span)
