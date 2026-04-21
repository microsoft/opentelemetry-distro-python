# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from opentelemetry.sdk.trace.export import SpanProcessor


class AgentFrameworkSpanProcessor(SpanProcessor):
    """SpanProcessor for Agent Framework.

    Kept for interface compatibility. Both ``on_start`` and ``on_end``
    are intentional no-ops.
    """

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name
        super().__init__()

    def on_start(self, span, parent_context):
        pass

    def on_end(self, span):
        pass
