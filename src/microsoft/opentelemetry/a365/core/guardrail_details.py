# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Data class for guardrail evaluation details."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardrailDetails:
    """Immutable input contract describing a guardrail evaluation.

    Attributes:
        target_type: What content is being guarded (e.g., "llm_input", "tool_call").
        decision_type: The guardian's decision (e.g., "allow", "deny").
        guardian_name: Human-readable guardian name.
        guardian_id: Unique guardian identifier.
        guardian_provider_name: Provider name (e.g., "azure.ai.content_safety").
        guardian_version: Guardian version string.
        target_id: ID of the targeted content.
        decision_reason: Human-readable decision reason.
        decision_code: Machine-readable decision code.
        policy_id: Triggered policy ID.
        policy_name: Triggered policy name.
        policy_version: Policy version.
        content_input_hash: Hash of input content for forensic correlation.
        content_modified: Whether the content was altered by the guardrail.
        external_event_id: External event ID for SIEM correlation.
    """

    target_type: str
    decision_type: str
    guardian_name: str | None = None
    guardian_id: str | None = None
    guardian_provider_name: str | None = None
    guardian_version: str | None = None
    target_id: str | None = None
    decision_reason: str | None = None
    decision_code: str | None = None
    policy_id: str | None = None
    policy_name: str | None = None
    policy_version: str | None = None
    content_input_hash: str | None = None
    content_modified: bool | None = None
    external_event_id: str | None = None
