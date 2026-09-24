# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Propagate A365 identity and baggage to recognized GenAI spans.

Existing span attributes are never overwritten.
"""

from __future__ import annotations

from opentelemetry import baggage, context
from opentelemetry.sdk.trace import SpanProcessor as BaseSpanProcessor

from microsoft.opentelemetry.a365.core.exporters._gen_ai_span_classifier import _classify_gen_ai_span
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
    GEN_AI_OPERATION_NAME_KEY,
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


# Baggage attributes for all recognized GenAI spans.
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

# Additional baggage attributes for invoke_agent spans.
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

        try:
            existing = getattr(span, "attributes", {}) or {}
        except Exception:
            existing = {}

        if ctx is None:
            baggage_map = {}
        else:
            try:
                baggage_map = baggage.get_all(ctx) or {}
            except Exception:
                baggage_map = {}

        classification = _classify_gen_ai_span(span, existing, baggage_map)
        if not classification.is_gen_ai_span:
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

        try:
            existing = getattr(span, "attributes", {}) or {}
        except Exception:
            existing = {}

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
