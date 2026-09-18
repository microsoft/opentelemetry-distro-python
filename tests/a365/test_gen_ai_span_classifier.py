# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from types import SimpleNamespace

from microsoft.opentelemetry.a365.core.constants import GEN_AI_OPERATION_NAME_KEY
from microsoft.opentelemetry.a365.core.exporters._gen_ai_span_classifier import (
    _classify_gen_ai_span,
)


def test_classifies_supported_scope_with_unknown_operation_as_gen_ai():
    span = SimpleNamespace(
        name="chain RunnableSequence",
        instrumentation_scope=SimpleNamespace(name="microsoft.opentelemetry._genai._langchain"),
    )

    classification = _classify_gen_ai_span(
        span,
        {GEN_AI_OPERATION_NAME_KEY: "chain"},
        {},
    )

    assert classification.is_gen_ai_span
    assert classification.operation_name is None
