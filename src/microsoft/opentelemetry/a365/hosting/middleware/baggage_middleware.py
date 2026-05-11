# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Middleware that propagates OpenTelemetry baggage context derived from TurnContext."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

try:
    from microsoft_agents.activity import ActivityEventNames, ActivityTypes
    from microsoft_agents.hosting.core.turn_context import TurnContext
except ImportError as exc:
    logging.getLogger(__name__).error(
        "microsoft.opentelemetry.a365.hosting requires the agents SDK "
        "(missing module: %s). Install it with: "
        "pip install microsoft-agents-activity microsoft-agents-hosting-core",
        exc.name,
    )

from microsoft.opentelemetry.a365.core.middleware.baggage_builder import BaggageBuilder

from microsoft.opentelemetry.a365.hosting.scope_helpers.populate_baggage import populate

# mypy: disable-error-code="call-arg"


class BaggageMiddleware:
    """Middleware that propagates OpenTelemetry baggage context derived from TurnContext.

    Async replies (ContinueConversation) are passed through without baggage setup.
    """

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
