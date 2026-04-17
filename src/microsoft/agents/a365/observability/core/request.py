# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# Request class.

from __future__ import annotations

from dataclasses import dataclass

from microsoft.agents.a365.observability.core.channel import Channel
from microsoft.agents.a365.observability.core.models.messages import InputMessagesParam


@dataclass
class Request:
    """Request details for agent execution."""

    content: InputMessagesParam | None = None
    session_id: str | None = None
    channel: Channel | None = None
    conversation_id: str | None = None
