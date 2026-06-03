# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Token resolver context types for contextual token resolution.

These types provide rich context to the token resolver delegate, including
the agent identity (agent ID + agentic user ID) and tenant ID.
"""

from __future__ import annotations

from typing import Optional


class AgentIdentity:
    """Represents the identity of an agent and its acting user.

    In the AI teammate scenario, ``agentic_user_id`` is 1:1 with ``agent_id``.
    In the S2S scenario, ``agentic_user_id`` will be None.
    """

    __slots__ = ("_agent_id", "_agentic_user_id")

    def __init__(self, agent_id: str, agentic_user_id: Optional[str] = None):
        """
        Args:
            agent_id: The agent identifier.
            agentic_user_id: The agentic user identifier (AAD Object ID),
                or None in S2S scenarios.
        """
        if not agent_id:
            raise ValueError("agent_id must be a non-empty string.")
        self._agent_id = agent_id
        self._agentic_user_id = agentic_user_id

    @property
    def agent_id(self) -> str:
        """The agent identifier."""
        return self._agent_id

    @property
    def agentic_user_id(self) -> Optional[str]:
        """The agentic user identifier (AAD Object ID).

        In the AI teammate scenario, this value is 1:1 with ``agent_id``.
        Will be None in the S2S scenario.
        """
        return self._agentic_user_id


class TokenResolverContext:
    """Provides contextual information to the token resolver delegate.

    ``identity`` provides first-class access to agent identity fields (agent ID,
    agentic user ID). ``tenant_id`` and ``identity`` together identify the cache key.
    """

    __slots__ = ("_identity", "_tenant_id")

    def __init__(self, identity: AgentIdentity, tenant_id: str):
        """
        Args:
            identity: The agent identity associated with this request.
            tenant_id: The tenant identifier (cache key).
        """
        if identity is None:
            raise ValueError("identity must be provided.")
        if not tenant_id:
            raise ValueError("tenant_id must be a non-empty string.")
        self._identity = identity
        self._tenant_id = tenant_id

    @property
    def identity(self) -> AgentIdentity:
        """The agent identity associated with this token resolution request.

        Contains the agent ID and agentic user ID (AAD Object ID) as first-class properties.
        """
        return self._identity

    @property
    def tenant_id(self) -> str:
        """The tenant identifier (part of the cache key)."""
        return self._tenant_id
