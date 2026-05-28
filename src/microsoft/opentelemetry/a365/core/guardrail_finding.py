# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Data class for a single guardrail security finding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardrailFinding:
    """A single security finding from a guardrail evaluation.

    Attributes:
        risk_category: Category of risk detected (e.g., "hate_speech", "pii", "jailbreak").
        risk_severity: Severity level (use GuardrailRiskSeverity constants).
        policy_decision_type: Per-finding decision override.
        policy_id: Policy that triggered this finding.
        policy_name: Policy name.
        policy_version: Policy version.
        risk_score: Confidence score from 0.0 to 1.0.
        risk_metadata: Non-PII structural metadata about the finding.
    """

    risk_category: str
    risk_severity: str
    policy_decision_type: str | None = None
    policy_id: str | None = None
    policy_name: str | None = None
    policy_version: str | None = None
    risk_score: float | None = None
    risk_metadata: list[str] | None = None
