# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Span enricher for LangChain.

Converts OTel-spec structured messages on invoke_agent spans back to
plain-string content arrays before export through the A365 pipeline,
matching the format the A365 backend expects.
"""

from __future__ import annotations

from microsoft.opentelemetry.a365.core.enricher_utils import extract_input_content, extract_output_content
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)
from microsoft.opentelemetry.a365.core.exporters.enriched_span import EnrichedReadableSpan
from opentelemetry.sdk.trace import ReadableSpan


def enrich_langchain_span(span: ReadableSpan) -> ReadableSpan:
    """Enricher for LangChain spans exported through the A365 pipeline.

    For invoke_agent spans, converts OTel-spec structured messages
    (``[{"role":"user","parts":[...]}]``) to plain content arrays
    (``["Hello"]``) that the A365 backend expects.
    """
    if not span.name.startswith(INVOKE_AGENT_OPERATION_NAME):
        return span

    attributes = span.attributes or {}
    extra_attributes: dict[str, str] = {}

    input_messages = attributes.get(GEN_AI_INPUT_MESSAGES_KEY)
    if input_messages:
        extra_attributes[GEN_AI_INPUT_MESSAGES_KEY] = extract_input_content(str(input_messages))

    output_messages = attributes.get(GEN_AI_OUTPUT_MESSAGES_KEY)
    if output_messages:
        extra_attributes[GEN_AI_OUTPUT_MESSAGES_KEY] = extract_output_content(str(output_messages))

    if extra_attributes:
        return EnrichedReadableSpan(span, extra_attributes)

    return span
