# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from microsoft_agents_a365.observability.core.constants import GEN_AI_OPERATION_NAME_KEY
from microsoft_agents_a365.observability.core.inference_operation_type import InferenceOperationType
from microsoft_agents_a365.observability.core.utils import extract_model_name
from opentelemetry import context as context_api
from opentelemetry.sdk.trace import ReadableSpan, Span
from opentelemetry.sdk.trace.export import SpanProcessor


class SemanticKernelSpanProcessor(SpanProcessor):
    """SpanProcessor for Semantic Kernel.

    Intercepts ``chat.*`` spans on start, renames them to
    ``"chat <model_name>"`` and sets ``gen_ai.operation.name``.
    """

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name

    def on_start(self, span: Span, parent_context: context_api.Context | None) -> None:
        if span.name.startswith("chat."):
            span.set_attribute(GEN_AI_OPERATION_NAME_KEY, InferenceOperationType.CHAT.value.lower())
            model_name = extract_model_name(span.name)
            span.update_name(f"{InferenceOperationType.CHAT.value.lower()} {model_name}")

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
