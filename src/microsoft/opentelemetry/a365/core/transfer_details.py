# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Explicit transfer metadata for execute-tool operations."""

from dataclasses import dataclass
from enum import Enum

from microsoft.opentelemetry.a365.core.agent_details import AgentDetails


class TransferMode(str, Enum):
    """How control passes to the transfer target."""

    RETURN_TO_CALLER = "return_to_caller"
    PASS_CONTROL = "pass_control"


class TransferTargetType(str, Enum):
    """Kind of target receiving control."""

    AGENT = "agent"
    HUMAN = "human"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class TransferDetails:
    """Explicit transfer mode and optional target agent identity.

    Only the target agent's ID, name, blueprint ID, platform ID and version
    are recorded. Agent details are not valid for human or workflow targets.
    """

    mode: TransferMode
    target_type: TransferTargetType = TransferTargetType.AGENT
    target_agent_details: AgentDetails | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TransferMode):
            raise TypeError("mode must be a TransferMode member.")
        if not isinstance(self.target_type, TransferTargetType):
            raise TypeError("target_type must be a TransferTargetType member.")
        if self.target_agent_details is not None and self.target_type != TransferTargetType.AGENT:
            raise ValueError("Target agent details can only be supplied for an agent transfer.")
