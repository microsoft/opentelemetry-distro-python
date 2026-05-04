# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

from collections.abc import Iterator

from microsoft.opentelemetry.a365.core.middleware.baggage_builder import BaggageBuilder

from microsoft.opentelemetry.a365.hosting.scope_helpers.utils import (
    get_caller_pairs,
    get_channel_pairs,
    get_conversation_pairs,
    get_target_agent_pairs,
    get_tenant_id_pair,
)
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from microsoft_agents.hosting.core.turn_context import TurnContext
else:  # pyright: ignore[reportUnreachable]
    try:
        from microsoft_agents.hosting.core.turn_context import TurnContext
    except ImportError:  # pragma: no cover - optional dependency
        # Stub silently; warning is emitted by the user-facing entry-point
        # (middleware/cache constructors) via HOSTING_INSTALL_HINT.
        TurnContext = None




def _iter_all_pairs(turn_context: TurnContext) -> Iterator[tuple[str, Any]]:
    activity = turn_context.activity
    if not activity:
        return
    yield from get_caller_pairs(activity)
    yield from get_target_agent_pairs(activity)
    yield from get_tenant_id_pair(activity)
    yield from get_channel_pairs(activity)
    yield from get_conversation_pairs(activity)


def populate(builder: BaggageBuilder, turn_context: TurnContext) -> BaggageBuilder:
    """Populate BaggageBuilder with baggage values extracted from a turn context.

    Args:
        builder: The BaggageBuilder instance to populate
        turn_context: The TurnContext containing activity information

    Returns:
        The updated BaggageBuilder instance (for method chaining)
    """
    builder.set_pairs(_iter_all_pairs(turn_context))
    return builder
