# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

# Re-export instrumentation utilities from azure-monitor-opentelemetry to avoid duplication.
from azure.monitor.opentelemetry._utils.instrumentation import (  # noqa: F401
    DependencyConflict,
    get_dist_dependency_conflicts,
    get_dependency_conflicts,
)

__all__ = [
    "DependencyConflict",
    "get_dist_dependency_conflicts",
    "get_dependency_conflicts",
]
