# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Middleware that propagates OpenTelemetry baggage context derived from TurnContext."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from microsoft.opentelemetry.a365.core.utils import warn_if_hosting_missing
from microsoft.opentelemetry.a365.core.middleware.baggage_builder import BaggageBuilder

from microsoft.opentelemetry.a365.hosting.scope_helpers.populate_baggage import populate

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from microsoft_agents.activity import ActivityEventNames, ActivityTypes
    from microsoft_agents.hosting.core.turn_context import TurnContext
else:  # pyright: ignore[reportUnreachable]
    try:
        from microsoft_agents.activity import ActivityEventNames, ActivityTypes
        from microsoft_agents.hosting.core.turn_context import TurnContext
    except ImportError:  # pragma: no cover - optional dependency
        # Stub silently; the warning is emitted in __init__ when the user
        # actually instantiates the middleware.
        ActivityEventNames = ActivityTypes = TurnContext = None

# mypy: disable-error-code="call-arg"

_logger = logging.getLogger(__name__)


class BaggageMiddleware:
    """Middleware that propagates OpenTelemetry baggage context derived from TurnContext.

    Async replies (ContinueConversation) are passed through without baggage setup.
    """

    def __init__(self) -> None:
        warn_if_hosting_missing(_logger, "microsoft_agents.activity", "microsoft_agents.hosting.core")

    async def on_turn(
        self,
        context: TurnContext,
        logic: Callable[[TurnContext], Awaitable],
    ) -> None:
        activity = context.activity
        is_async_reply = (
            activity is not None
            and activity.type == ActivityTypes.event
            and activity.name == ActivityEventNames.continue_conversation
        )

        if is_async_reply:
            await logic()
            return

        builder = BaggageBuilder()
        populate(builder, context)
        baggage_scope = builder.build()

        with baggage_scope:
            await logic()
