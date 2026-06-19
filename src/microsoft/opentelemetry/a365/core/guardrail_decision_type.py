# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""String constants for guardrail decision types."""


class GuardrailDecisionType:
    """Well-known guardrail decision type values."""

    #: Allow the content to proceed unchanged.
    ALLOW = "allow"
    #: Allow the content but record it for auditing.
    AUDIT = "audit"
    #: Block the content.
    DENY = "deny"
    #: Allow the content after modifying it.
    MODIFY = "modify"
    #: Allow the content but surface a warning.
    WARN = "warn"
