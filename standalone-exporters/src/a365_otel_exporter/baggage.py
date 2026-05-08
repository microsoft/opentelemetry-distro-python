"""Baggage helpers for propagating A365 context through OpenTelemetry spans."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from opentelemetry import baggage, context
from opentelemetry.trace import Span

logger = logging.getLogger(__name__)

# Baggage / attribute key constants.
BAGGAGE_TENANT_ID = "tenant_id"
BAGGAGE_AGENT_ID = "agent_id"
BAGGAGE_CONVERSATION_ID = "conversation_id"

# Span attribute keys that the exporter reads when grouping spans.
ATTR_TENANT_ID = "a365.tenant_id"
ATTR_AGENT_ID = "a365.agent_id"
ATTR_CONVERSATION_ID = "a365.conversation_id"


class BaggageBuilder:
    """Build an OpenTelemetry context with A365 baggage entries.

    Usage::

        builder = BaggageBuilder().tenant_id("...").agent_id("...")
        with builder.build():
            # spans created here carry A365 baggage
            ...

    The builder also injects the values as span attributes on every span
    created within the context so that the exporter can read them without
    relying on baggage propagation alone.
    """

    def __init__(self) -> None:
        self._tenant_id: Optional[str] = None
        self._agent_id: Optional[str] = None
        self._conversation_id: Optional[str] = None

    def tenant_id(self, value: str) -> "BaggageBuilder":
        """Set the tenant ID baggage entry."""
        self._tenant_id = value
        return self

    def agent_id(self, value: str) -> "BaggageBuilder":
        """Set the agent ID baggage entry."""
        self._agent_id = value
        return self

    def conversation_id(self, value: str) -> "BaggageBuilder":
        """Set the conversation ID baggage entry (optional)."""
        self._conversation_id = value
        return self

    @contextmanager
    def build(self) -> Iterator[context.Context]:
        """Return a context manager that activates the A365 baggage context.

        Yields the new ``Context`` for callers that need to pass it
        explicitly (e.g. to ``tracer.start_span(context=ctx)``).
        """
        ctx = context.get_current()

        if self._tenant_id is not None:
            ctx = baggage.set_baggage(BAGGAGE_TENANT_ID, self._tenant_id, context=ctx)
        if self._agent_id is not None:
            ctx = baggage.set_baggage(BAGGAGE_AGENT_ID, self._agent_id, context=ctx)
        if self._conversation_id is not None:
            ctx = baggage.set_baggage(BAGGAGE_CONVERSATION_ID, self._conversation_id, context=ctx)

        token = context.attach(ctx)
        try:
            yield ctx
        finally:
            context.detach(token)


def set_a365_span_attributes(
    span: Span,
    tenant_id: str,
    agent_id: str,
    conversation_id: Optional[str] = None,
) -> None:
    """Set A365 routing attributes directly on a span.

    Use this helper when baggage propagation is not available (e.g. when
    spans are created in a context where baggage has already been consumed
    or in fire-and-forget background tasks).

    Parameters
    ----------
    span:
        The span to annotate.
    tenant_id:
        Azure AD tenant ID that owns the agent.
    agent_id:
        Agent 365 agent ID.
    conversation_id:
        Optional conversation ID for grouping related spans.
    """
    span.set_attribute(ATTR_TENANT_ID, tenant_id)
    span.set_attribute(ATTR_AGENT_ID, agent_id)
    if conversation_id is not None:
        span.set_attribute(ATTR_CONVERSATION_ID, conversation_id)
