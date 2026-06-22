# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""String constants for guardrail risk severity levels."""


class GuardrailRiskSeverity:
    """Well-known risk severity level values."""

    #: No risk detected.
    NONE = "none"
    #: Low-severity risk.
    LOW = "low"
    #: Medium-severity risk.
    MEDIUM = "medium"
    #: High-severity risk.
    HIGH = "high"
    #: Critical-severity risk.
    CRITICAL = "critical"
