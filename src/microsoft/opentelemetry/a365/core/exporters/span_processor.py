# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Span processor for propagating OpenTelemetry baggage entries onto spans.

For every recognized GenAI span:
  * Retrieve the current (or parent) context
  * Obtain all baggage entries
  * For each documented key with a truthy value not already present as a span
    attribute, add it via span.set_attribute
  * Never overwrites existing attributes
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry import baggage, context
from opentelemetry.sdk.trace import SpanProcessor as BaseSpanProcessor

from microsoft.opentelemetry.a365.constants import (
    CHANNEL_LINK_KEY,
    CHANNEL_NAME_KEY,
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
    GEN_AI_OPERATION_NAME_KEY,
    APPLY_GUARDRAIL_OPERATION_NAME,
    CHAT_OPERATION_NAME,
    EXECUTE_TOOL_OPERATION_NAME,
    OUTPUT_MESSAGES_OPERATION_NAME,
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
from microsoft.opentelemetry.a365.core.inference_operation_type import InferenceOperationType

# mypy: disable-error-code="no-untyped-def"

# Processor-only operation names used to classify qualifying GenAI spans.
GEN_AI_RECOGNIZED_OPERATION_NAMES: frozenset[str] = frozenset(
    {
        INVOKE_AGENT_OPERATION_NAME,
        EXECUTE_TOOL_OPERATION_NAME,
        OUTPUT_MESSAGES_OPERATION_NAME,
        CHAT_OPERATION_NAME,
        APPLY_GUARDRAIL_OPERATION_NAME,
    }
    | {operation.value for operation in InferenceOperationType}
)


# Generic / common tracing attributes propagated from baggage to qualifying GenAI spans
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


def _matches_operation_name(span: Any, existing_attributes: Mapping[str, object], operation_name: str) -> bool:
    existing_operation_name = existing_attributes.get(GEN_AI_OPERATION_NAME_KEY)
    if existing_operation_name:
        return existing_operation_name == operation_name

    span_name = getattr(span, "name", None)
    return isinstance(span_name, str) and (span_name == operation_name or span_name.startswith(f"{operation_name} "))


def _is_gen_ai_span(span: Any, existing_attributes: Mapping[str, object]) -> bool:
    operation_name = existing_attributes.get(GEN_AI_OPERATION_NAME_KEY)
    if operation_name:
        return operation_name in GEN_AI_RECOGNIZED_OPERATION_NAMES

    span_name = getattr(span, "name", None)
    if not isinstance(span_name, str):
        return False

    return any(
        span_name == operation_name or span_name.startswith(f"{operation_name} ")
        for operation_name in GEN_AI_RECOGNIZED_OPERATION_NAMES
    )


# pylint: disable=broad-exception-caught, too-many-branches, useless-parent-delegation
# pylint: disable=global-statement
class A365SpanProcessor(BaseSpanProcessor):
    """Span processor that stamps agent identity and propagates baggage to span attributes.

    Static identity (tenant_id, agent_id) is set from configuration on qualifying GenAI spans.
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

        if not _is_gen_ai_span(span, existing):
            return super().on_start(span, parent_context)

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

        is_invoke_agent = _matches_operation_name(span, existing, INVOKE_AGENT_OPERATION_NAME)
        target_keys = list(COMMON_ATTRIBUTES)
        if is_invoke_agent:
            for k in INVOKE_AGENT_ATTRIBUTES:
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
