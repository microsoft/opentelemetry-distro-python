# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Microsoft Agent 365 Observability Hosting Library.
"""

from microsoft.agents.a365.observability.hosting.middleware.baggage_middleware import BaggageMiddleware
from microsoft.agents.a365.observability.hosting.middleware.observability_hosting_manager import (
    ObservabilityHostingManager,
    ObservabilityHostingOptions,
)
from microsoft.agents.a365.observability.hosting.middleware.output_logging_middleware import (
    A365_PARENT_TRACEPARENT_KEY,
    OutputLoggingMiddleware,
)

__all__ = [
    "BaggageMiddleware",
    "OutputLoggingMiddleware",
    "A365_PARENT_TRACEPARENT_KEY",
    "ObservabilityHostingManager",
    "ObservabilityHostingOptions",
]
