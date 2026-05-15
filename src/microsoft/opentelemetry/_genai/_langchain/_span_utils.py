# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Compatibility shim for ``opentelemetry.util.genai.span_utils``.

The functions below are expected by :class:`LangChainTracer` but do not yet
exist in the published ``opentelemetry-util-genai`` package (0.4b0).  They
operate on bare :class:`~opentelemetry.trace.Span` objects and an
:class:`~opentelemetry.util.genai.types.LLMInvocation` dataclass, bridging
LangChain run data to OTel attributes.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from opentelemetry._logs import LogRecord
from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_FREQUENCY_PENALTY,
    GEN_AI_REQUEST_MAX_TOKENS,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_PRESENCE_PENALTY,
    GEN_AI_REQUEST_SEED,
    GEN_AI_REQUEST_STOP_SEQUENCES,
    GEN_AI_REQUEST_TEMPERATURE,
    GEN_AI_REQUEST_TOP_P,
    GEN_AI_RESPONSE_ID,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GenAiOperationNameValues,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.server_attributes import SERVER_ADDRESS, SERVER_PORT
from opentelemetry.trace import Span
from opentelemetry.trace.status import Status, StatusCode
from opentelemetry.util.genai.types import Error, LLMInvocation
from opentelemetry.util.genai.utils import (
    gen_ai_json_dumps,
    is_experimental_mode,
    should_emit_event,
)

logger = logging.getLogger(__name__)


def _apply_error_attributes(span: Span, error: Error) -> None:
    """Set error status and ``error.type`` attribute on *span*."""
    error_type = error.type.__qualname__
    span.set_status(Status(StatusCode.ERROR, error.message))
    span.set_attribute(ERROR_TYPE, error_type)


def _apply_llm_finish_attributes(span: Span, invocation: LLMInvocation) -> None:
    """Apply LLM response attributes from *invocation* onto *span*.

    This mirrors the attribute-setting logic of
    ``InferenceInvocation._apply_finish`` but works with a standalone
    ``Span`` and the lightweight ``LLMInvocation`` dataclass used by the
    LangChain tracer.
    """
    _operation_name = GenAiOperationNameValues.CHAT.value

    attrs: dict[str, Any] = {GEN_AI_OPERATION_NAME: _operation_name}

    _optional = (
        (GEN_AI_REQUEST_MODEL, invocation.request_model),
        (GEN_AI_PROVIDER_NAME, invocation.provider),
        (SERVER_ADDRESS, invocation.server_address),
        (SERVER_PORT, invocation.server_port),
        (GEN_AI_REQUEST_TEMPERATURE, invocation.temperature),
        (GEN_AI_REQUEST_TOP_P, invocation.top_p),
        (GEN_AI_REQUEST_FREQUENCY_PENALTY, invocation.frequency_penalty),
        (GEN_AI_REQUEST_PRESENCE_PENALTY, invocation.presence_penalty),
        (GEN_AI_REQUEST_MAX_TOKENS, invocation.max_tokens),
        (GEN_AI_REQUEST_STOP_SEQUENCES, invocation.stop_sequences),
        (GEN_AI_REQUEST_SEED, invocation.seed),
        (GEN_AI_RESPONSE_MODEL, invocation.response_model_name),
        (GEN_AI_RESPONSE_ID, invocation.response_id),
        (GEN_AI_USAGE_INPUT_TOKENS, invocation.input_tokens),
        (GEN_AI_USAGE_OUTPUT_TOKENS, invocation.output_tokens),
    )
    attrs.update({k: v for k, v in _optional if v is not None})

    # Finish reasons from output messages
    finish_reasons = invocation.finish_reasons
    if not finish_reasons and invocation.output_messages:
        finish_reasons = [
            msg.finish_reason
            for msg in invocation.output_messages
            if msg.finish_reason
        ] or None
    if finish_reasons:
        from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
            GEN_AI_RESPONSE_FINISH_REASONS,
        )
        attrs[GEN_AI_RESPONSE_FINISH_REASONS] = finish_reasons

    # Structured message content on spans.
    # The LangChain tracer always captures messages (the content-capture gate
    # is handled at a higher level by the A365 pipeline / enriching processor).
    from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
        GEN_AI_INPUT_MESSAGES,
        GEN_AI_OUTPUT_MESSAGES,
        GEN_AI_SYSTEM_INSTRUCTIONS,
    )

    def _serialize(items: list) -> str | None:
        if not items:
            return None
        return gen_ai_json_dumps([asdict(item) for item in items])

    if val := _serialize(invocation.input_messages):
        attrs[GEN_AI_INPUT_MESSAGES] = val
    if val := _serialize(invocation.output_messages):
        attrs[GEN_AI_OUTPUT_MESSAGES] = val
    if val := _serialize(invocation.system_instruction):
        attrs[GEN_AI_SYSTEM_INSTRUCTIONS] = val

    # Extra attributes stored on the invocation
    attrs.update(invocation.attributes)

    span.set_attributes(attrs)


def _maybe_emit_llm_event(
    event_logger: Any,
    span: Span,
    invocation: LLMInvocation,
) -> None:
    """Emit a ``gen_ai.client.inference.operation.details`` log event if configured."""
    if not is_experimental_mode() or not should_emit_event():
        return

    from opentelemetry.trace import get_current_span, set_span_in_context

    attrs: dict[str, Any] = {}
    attrs[GEN_AI_OPERATION_NAME] = GenAiOperationNameValues.CHAT.value
    if invocation.request_model:
        attrs[GEN_AI_REQUEST_MODEL] = invocation.request_model
    if invocation.provider:
        attrs[GEN_AI_PROVIDER_NAME] = invocation.provider

    # Serialize messages for event (as list of dicts, not JSON strings)
    if invocation.input_messages:
        from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import GEN_AI_INPUT_MESSAGES
        attrs[GEN_AI_INPUT_MESSAGES] = [asdict(m) for m in invocation.input_messages]
    if invocation.output_messages:
        from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import GEN_AI_OUTPUT_MESSAGES
        attrs[GEN_AI_OUTPUT_MESSAGES] = [asdict(m) for m in invocation.output_messages]

    span_context = set_span_in_context(span)
    log_record = LogRecord(
        event_name="gen_ai.client.inference.operation.details",
        attributes=attrs,
        context=span_context,
    )
    event_logger.emit(log_record)
