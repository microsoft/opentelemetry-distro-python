# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Observability helper utilities for creating observability objects.
"""

from dataclasses import dataclass
import logging
from os import environ
from typing import TYPE_CHECKING, Any

from services.guardrail_service import SAMPLE_INPUT_VALUE

if TYPE_CHECKING:
    from microsoft_agents.hosting.core import TurnContext
else:
    TurnContext = Any

try:
    from microsoft_agents_a365.observability.core.agent_details import AgentDetails
    from microsoft_agents_a365.observability.core.request import Request
except ModuleNotFoundError:
    @dataclass
    class AgentDetails:
        agent_id: str
        agent_name: str
        agent_description: str | None = None
        agent_blueprint_id: str | None = None
        tenant_id: str | None = None

    @dataclass
    class Request:
        content: str | None = None
        session_id: str | None = None

logger = logging.getLogger(__name__)


def create_agent_details(context: TurnContext) -> AgentDetails:
    """Create agent details for observability."""
    tenant_id = None
    if context.activity.recipient and hasattr(context.activity.recipient, "tenant_id"):
        tenant_id = context.activity.recipient.tenant_id
    if not tenant_id:
        tenant_id = environ.get("TENANT_ID", "default-tenant")

    return AgentDetails(
        agent_id=context.activity.recipient.agentic_app_id,
        agent_name=environ.get("AGENT_NAME", "Azure OpenAI Agent"),
        agent_description="An AI agent powered by Azure OpenAI",
        agent_blueprint_id="4a380e3b-7092-4d73-bb9d-b6a54702684af",
        tenant_id=tenant_id,
    )


def create_request_details(session_id: str | None = None) -> Request:
    """Create request details with non-sensitive sample content for observability."""
    return Request(
        content=SAMPLE_INPUT_VALUE,
        session_id=session_id,
    )
