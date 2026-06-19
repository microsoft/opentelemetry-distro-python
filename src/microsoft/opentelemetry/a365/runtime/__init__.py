# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Runtime helpers for Agent365 observability.

Utilities for resolving the runtime environment, discovering Power Platform
API endpoints, and modelling operation results used when configuring Agent365
telemetry.
"""

from microsoft.opentelemetry.a365.runtime.environment_utils import get_observability_authentication_scope
from microsoft.opentelemetry.a365.runtime.operation_error import OperationError
from microsoft.opentelemetry.a365.runtime.operation_result import OperationResult
from microsoft.opentelemetry.a365.runtime.power_platform_api_discovery import (
    ClusterCategory,
    PowerPlatformApiDiscovery,
)
from microsoft.opentelemetry.a365.runtime.utility import Utility

__all__ = [
    "get_observability_authentication_scope",
    "PowerPlatformApiDiscovery",
    "ClusterCategory",
    "Utility",
    "OperationError",
    "OperationResult",
]
