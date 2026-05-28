# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""String constants for guardrail decision types."""


class GuardrailDecisionType:
    """Well-known guardrail decision type values."""

    ALLOW = "allow"
    AUDIT = "audit"
    DENY = "deny"
    MODIFY = "modify"
    WARN = "warn"
