# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""LangChain BaseTracer that emits OpenTelemetry spans."""

import logging
import re
from collections import OrderedDict
from dataclasses import asdict
from collections.abc import Iterator
from itertools import chain
from threading import RLock
from contextvars import Token
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)
from uuid import UUID

from langchain_core.tracers import BaseTracer
from langchain_core.tracers.schemas import Run
from opentelemetry import context as context_api
from opentelemetry import trace as trace_api
from opentelemetry.context import (
    _SUPPRESS_INSTRUMENTATION_KEY,
    get_value,
)
from opentelemetry.trace import Span, SpanKind
from opentelemetry.util.genai.span_utils import (
    _apply_error_attributes,
    _apply_llm_finish_attributes,
    _maybe_emit_llm_event,
)
from opentelemetry.util.genai.types import Error, LLMInvocation
from opentelemetry.util.types import AttributeValue

from microsoft.opentelemetry._genai._langchain._utils import (
    DictWithLock,
    as_utc_nano,
    build_llm_invocation,
    flatten,
    safe_json_dumps,
    IGNORED_EXCEPTION_PATTERNS,
    CHAT_OPERATION_NAME,
    INVOKE_AGENT_OPERATION_NAME,
    EXECUTE_TOOL_OPERATION_NAME,
    GEN_AI_AGENT_DESCRIPTION_KEY,
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
    GEN_AI_PROVIDER_NAME_KEY,
    GEN_AI_REQUEST_CHOICE_COUNT_KEY,
    GEN_AI_REQUEST_MODEL_KEY,
    GEN_AI_TOOL_DEFINITIONS_KEY,
    GEN_AI_USAGE_INPUT_TOKENS_KEY,
    GEN_AI_USAGE_OUTPUT_TOKENS_KEY,
    SERVER_ADDRESS_KEY,
    SERVER_PORT_KEY,
    add_operation_type,
    chain_node_messages,
    extract_agent_metadata,
    extract_session_info,
    function_calls,
    invocation_parameters,
    llm_provider,
    metadata,
    model_name,
    prompts,
    _extract_structured_output_messages,
    _extract_agent_input_messages,
    _extract_agent_output_messages,
    _output_message_to_input,
    _seed_initial_messages,
    _should_capture_content_on_spans,
    _tool_run_to_input_message,
    token_counts,
    tools,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


CONTEXT_ATTRIBUTES = (
    "session.id",
    "user.id",
    "metadata",
    "tag.tags",
    "llm.prompt_template.template",
    "llm.prompt_template.variables",
    "llm.prompt_template.version",
)


# pylint: disable=broad-exception-caught, too-many-branches, too-many-statements
class LangChainTracer(BaseTracer):  # pylint: disable=too-many-ancestors, too-many-instance-attributes
    _MAX_TRACKED_RUNS = 10000

    run_inline = True

    __slots__ = (
        "_tracer",
        "_separate_trace_from_runtime_context",
        "_agent_config",
        "_agent_run_ids",
        "_agent_content",
        "_agent_wrapper_spans",
        "_spans_by_run",
        "_event_logger",
        "_context_tokens",
    )

    def __init__(
        self,
        tracer: trace_api.Tracer,
        separate_trace_from_runtime_context: bool,
        *args: Any,
        agent_config: dict[str, Any] | None = None,
        event_logger: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if TYPE_CHECKING:
            assert self.run_map  # type: ignore[has-type]
        self.run_map = DictWithLock[str, Run](self.run_map)  # type: ignore[has-type,misc]
        self._tracer = tracer
        self._separate_trace_from_runtime_context = separate_trace_from_runtime_context
        self._agent_config: dict[str, Any] = agent_config or {}
        self._agent_run_ids: set[UUID] = set()
        self._agent_content: dict[UUID, dict[str, Any]] = {}
        self._agent_wrapper_spans: dict[UUID, Span] = {}
        self._spans_by_run: OrderedDict[UUID, Span] = OrderedDict()
        self._event_logger = event_logger
        self._context_tokens: dict[UUID, list[Token]] = {}
        self._lock = RLock()  # type: ignore[misc]

    def get_span(self, run_id: UUID) -> Span | None:
        with self._lock:
            return self._spans_by_run.get(run_id)

    def _evict_tracked_runs(self) -> None:
        """Evict oldest entries from _spans_by_run and clean up all related state.

        This prevents unbounded memory growth in long-running agents by ensuring
        that when spans are evicted from the primary tracking dict, corresponding
        entries in all auxiliary dictionaries are also removed.

        Acquires ``self._lock`` internally so eviction is always atomic
        regardless of call site.
        """
        with self._lock:
            while len(self._spans_by_run) > self._MAX_TRACKED_RUNS:
                evicted_id, _ = self._spans_by_run.popitem(last=False)
                self._agent_run_ids.discard(evicted_id)
                self._agent_content.pop(evicted_id, None)
                self._agent_wrapper_spans.pop(evicted_id, None)
                self._context_tokens.pop(evicted_id, None)
                self.run_map.pop(str(evicted_id), None)

    def _start_trace(self, run: Run) -> None:
        self.run_map[str(run.id)] = run
        if context_api.get_value(_SUPPRESS_INSTRUMENTATION_KEY):
            return
        with self._lock:
            parent_context = (
                trace_api.set_span_in_context(parent)
                if (parent_run_id := run.parent_run_id) and (parent := self._spans_by_run.get(parent_run_id))
                else (context_api.Context() if self._separate_trace_from_runtime_context else None)
            )
        start_time_utc_nano = as_utc_nano(run.start_time)

        is_agent = self._is_agent_run(run)
        # Nested agents (sub-agents with an agent ancestor) must NOT inherit
        # their identity from the shared ``_agent_config`` — that describes
        # the top-level agent only.
        is_nested_agent = is_agent and self._find_agent_ancestor(run) is not None

        # Determine span name based on run type
        if is_agent:
            agent_name = self._resolve_agent_name(run, use_config=not is_nested_agent)
            span_name = (
                f"{INVOKE_AGENT_OPERATION_NAME} {agent_name}"
                if agent_name
                else f"{INVOKE_AGENT_OPERATION_NAME} {run.name}"
            )
        elif run.run_type.lower() == "tool":
            span_name = f"{EXECUTE_TOOL_OPERATION_NAME} {run.name}"
        else:
            span_name = run.name

        # For agent runs, always create a wrapper span.
        # The wrapper gets the agent name (from config or metadata).
        # The inner span shows the framework name (e.g. "invoke_agent LangGraph").
        wrapper_span: Span | None = None
        if is_agent:
            agent_name = self._resolve_agent_name(run, use_config=not is_nested_agent)
            wrapper_label = agent_name or run.name
            wrapper_span = self._tracer.start_span(
                name=f"{INVOKE_AGENT_OPERATION_NAME} {wrapper_label}",
                context=parent_context,
                start_time=start_time_utc_nano,
                kind=SpanKind.INTERNAL,
            )
            # Set agent attributes on wrapper span BEFORE creating the inner
            # span so that GenAIMainAgentSpanProcessor.on_start can read them
            # from the parent when the inner span is created.
            wrapper_span.set_attribute(GEN_AI_OPERATION_NAME_KEY, INVOKE_AGENT_OPERATION_NAME)
            if agent_name:
                wrapper_span.set_attribute(GEN_AI_AGENT_NAME_KEY, agent_name)
            # Apply agent identity from config only for the top-level agent.
            # Nested agents derive identity solely from run metadata.
            if not is_nested_agent:
                agent_id = self._agent_config.get("agent_id")
                if agent_id:
                    wrapper_span.set_attribute(GEN_AI_AGENT_ID_KEY, agent_id)
                agent_desc = self._agent_config.get("agent_description")
                if agent_desc:
                    wrapper_span.set_attribute(GEN_AI_AGENT_DESCRIPTION_KEY, agent_desc)
                agent_version = self._agent_config.get("agent_version")
                if agent_version:
                    wrapper_span.set_attribute(GEN_AI_AGENT_VERSION_KEY, agent_version)
            wrapper_span.set_attributes(dict(flatten(extract_agent_metadata(run))))
            server_addr = self._agent_config.get("server_address")
            if server_addr:
                wrapper_span.set_attribute(SERVER_ADDRESS_KEY, server_addr)
            server_port = self._agent_config.get("server_port")
            if server_port:
                wrapper_span.set_attribute(SERVER_PORT_KEY, server_port)
            wrapper_span.set_attributes(dict(flatten(extract_session_info(run))))

            parent_context = trace_api.set_span_in_context(wrapper_span)
            # Resolve framework name for the inner span (e.g. "LangGraph")
            framework_name = self._resolve_framework_name(run)
            span_name = f"{INVOKE_AGENT_OPERATION_NAME} {framework_name}"

        if run.run_type.lower() in ("llm", "chat_model"):
            span_kind = SpanKind.CLIENT
        else:
            span_kind = SpanKind.INTERNAL

        span = self._tracer.start_span(
            name=span_name,
            context=parent_context,
            start_time=start_time_utc_nano,
            kind=span_kind,
        )

        if not self._separate_trace_from_runtime_context:
            token = context_api.attach(trace_api.set_span_in_context(span))
            with self._lock:
                self._context_tokens[run.id] = [token]

        # For agent spans, init content aggregation tracking
        if is_agent:
            with self._lock:
                self._agent_run_ids.add(run.id)
                self._agent_content[run.id] = {
                    "input_messages": [],
                    "output_messages": [],
                    "pending_assistant": None,
                    "seeded_initial": False,
                    "model": None,
                    "provider": None,
                    "request_choice_count": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
                if wrapper_span is not None:
                    self._agent_wrapper_spans[run.id] = wrapper_span

        with self._lock:
            self._spans_by_run[run.id] = span
        self._evict_tracked_runs()

    def _end_trace(self, run: Run) -> None:
        self.run_map.pop(str(run.id), None)
        if context_api.get_value(_SUPPRESS_INSTRUMENTATION_KEY):
            return

        is_agent = run.id in self._agent_run_ids

        # Aggregate child content into parent agent span
        if not is_agent and run.parent_run_id:
            self._aggregate_into_parent(run)

        with self._lock:
            span = self._spans_by_run.pop(run.id, None)
            wrapper_span = self._agent_wrapper_spans.pop(run.id, None) if is_agent else None
            tokens = self._context_tokens.pop(run.id, None)

        if tokens:
            runtime_ctx = getattr(context_api, "_RUNTIME_CONTEXT", None)
            for token in reversed(tokens):
                try:
                    if runtime_ctx is not None:
                        runtime_ctx.detach(token)
                    else:
                        context_api.detach(token)
                except ValueError:
                    logger.debug("Failed to detach LangChain run context.", exc_info=True)

        end_time_utc_nano = as_utc_nano(run.end_time) if run.end_time else None

        if span:
            invocation: LLMInvocation | None = None
            try:
                if is_agent and wrapper_span:
                    # Two-span agent: update inner span as chain, finalize wrapper as agent
                    _update_span(span, run)
                elif is_agent:
                    # Single-span agent: finalize directly
                    self._finalize_agent_span(span, run)
                else:
                    invocation = _update_span(span, run)
            except Exception:
                logger.exception("Failed to update span with run data.")
            # Emit OTel GenAI event for LLM spans (respects env-var config)
            if invocation is not None and self._event_logger is not None:
                try:
                    _maybe_emit_llm_event(self._event_logger, span, invocation)
                except Exception:
                    logger.debug("Failed to emit LLM event.", exc_info=True)
            span.end(end_time=end_time_utc_nano)

        # Finalize and end wrapper span after the inner span
        if wrapper_span:
            try:
                self._finalize_agent_span(wrapper_span, run)
            except Exception:
                logger.exception("Failed to finalize agent wrapper span.")
            wrapper_span.end(end_time=end_time_utc_nano)

        # Clean up agent tracking
        if is_agent:
            with self._lock:
                self._agent_run_ids.discard(run.id)
                self._agent_content.pop(run.id, None)

    def _persist_run(self, run: Run) -> None:
        pass

    def on_llm_error(self, error: BaseException, *args: Any, run_id: UUID, **kwargs: Any) -> Run:
        with self._lock:
            span = self._spans_by_run.get(run_id)
        if span:
            span.record_exception(error)
            _apply_error_attributes(span, Error(message=str(error), type=type(error)))
        return super().on_llm_error(error, *args, run_id=run_id, **kwargs)

    def on_chain_error(self, error: BaseException, *args: Any, run_id: UUID, **kwargs: Any) -> Run:
        with self._lock:
            span = self._spans_by_run.get(run_id)
        if span:
            span.record_exception(error)
            _apply_error_attributes(span, Error(message=str(error), type=type(error)))
        return super().on_chain_error(error, *args, run_id=run_id, **kwargs)

    def on_retriever_error(self, error: BaseException, *args: Any, run_id: UUID, **kwargs: Any) -> Run:
        with self._lock:
            span = self._spans_by_run.get(run_id)
        if span:
            span.record_exception(error)
            _apply_error_attributes(span, Error(message=str(error), type=type(error)))
        return super().on_retriever_error(error, *args, run_id=run_id, **kwargs)

    def on_tool_error(self, error: BaseException, *args: Any, run_id: UUID, **kwargs: Any) -> Run:
        with self._lock:
            span = self._spans_by_run.get(run_id)
        if span:
            span.record_exception(error)
            _apply_error_attributes(span, Error(message=str(error), type=type(error)))
        return super().on_tool_error(error, *args, run_id=run_id, **kwargs)

    # ---- Agent detection & aggregation ----------------------------------------

    @staticmethod
    def _is_agent_like_chain(run: Run) -> bool:
        """Check whether a chain matches agent-like criteria (LangGraph, etc.)."""
        if run.run_type != "chain":
            return False
        if run.name == "LangGraph":
            return True
        serialized = run.serialized or {}
        graph_type = serialized.get("graph", {}).get("type") if isinstance(serialized.get("graph"), dict) else None
        if graph_type in ("CompiledGraph", "StateGraph"):
            return True
        if "agent" in run.name.lower():
            return True
        # LangChain create_agent sets lc_agent_name in metadata
        if run.extra and isinstance(run.extra, dict):
            meta = run.extra.get("metadata")
            if isinstance(meta, dict) and meta.get("lc_agent_name"):
                return True
        return False

    def _is_agent_run(self, run: Run) -> bool:
        """Detect whether a LangChain run should be the top-level agent span."""
        if not self._is_agent_like_chain(run):
            return False
        # Don't nest agents — if any ancestor is already an agent, this is internal
        if self._find_agent_ancestor(run) is not None:
            return False
        return True

    def _resolve_agent_name(self, run: Run, *, use_config: bool = True) -> str | None:
        """Resolve agent name from config override, run metadata, or run name.

        Args:
            run: The LangChain run.
            use_config: Whether to check ``_agent_config`` first.  Pass
                ``False`` for nested (sub-) agents so their identity is
                derived from the run's own metadata rather than the shared
                top-level config.
        """
        # 1. Explicit config override (top-level agent only)
        if use_config:
            if name := self._agent_config.get("agent_name"):
                return str(name)
        # 2. From run metadata (agent_name or lc_agent_name)
        if run.extra and isinstance(run.extra, dict):
            meta = run.extra.get("metadata")
            if isinstance(meta, dict):
                if name := meta.get("agent_name"):
                    return str(name)
                if name := meta.get("lc_agent_name"):
                    return str(name)
        # 3. From serialized graph name
        if run.serialized and isinstance(run.serialized, dict):
            if name := run.serialized.get("name"):
                if name != "LangGraph":  # avoid generic name
                    return str(name)
        # 4. Run name itself if it's not just "LangGraph"
        if run.name and run.name != "LangGraph":
            return str(run.name)
        return None

    @staticmethod
    def _resolve_framework_name(run: Run) -> str:
        """Resolve the framework/graph type name for the inner agent span."""
        serialized = run.serialized or {}
        graph = serialized.get("graph")
        if isinstance(graph, dict):
            graph_type = graph.get("type")
            if graph_type in ("CompiledGraph", "StateGraph"):
                return "LangGraph"
        if serialized.get("name") and serialized["name"] != run.name:
            return str(serialized["name"])
        return "LangGraph"

    def _aggregate_into_parent(self, run: Run) -> None:  # pylint: disable=too-many-branches
        """Aggregate child run content into the parent agent span's content."""
        parent_id = run.parent_run_id
        if not parent_id:
            return
        # Walk up to find the nearest agent ancestor
        agent_id = self._find_agent_ancestor(run)
        if not agent_id:
            return

        run_type = run.run_type.lower()

        with self._lock:
            content = self._agent_content.get(agent_id)
            if not content:
                return

            # Capture model name from LLM runs
            if run_type in ("llm", "chat_model") and not content.get("model"):
                for _, m in model_name(run.outputs, run.extra):
                    content["model"] = m
                    break

            if run_type in ("llm", "chat_model") and not content.get("provider"):
                for _, provider in llm_provider(run.extra):
                    content["provider"] = provider
                    break

            if run_type in ("llm", "chat_model"):
                for key, val in invocation_parameters(run):
                    if key == GEN_AI_REQUEST_CHOICE_COUNT_KEY and isinstance(val, int) and val > 0:
                        previous = content.get("request_choice_count")
                        if not isinstance(previous, int) or val > previous:
                            content["request_choice_count"] = val
                    elif key == GEN_AI_TOOL_DEFINITIONS_KEY and val and not content.get("tool_definitions"):
                        # First LLM child with tool defs wins; downstream calls
                        # in an agent loop expose the same tool set.
                        content["tool_definitions"] = val

            if run_type in ("llm", "chat_model") and run.outputs:
                for key, val in token_counts(run.outputs):
                    if key == GEN_AI_USAGE_INPUT_TOKENS_KEY and isinstance(val, int):
                        content["input_tokens"] = content.get("input_tokens", 0) + val
                    elif key == GEN_AI_USAGE_OUTPUT_TOKENS_KEY and isinstance(val, int):
                        content["output_tokens"] = content.get("output_tokens", 0) + val

            # Build gen_ai.input.messages incrementally from agent children
            # so it matches the OTel GenAI semconv: ordered list of user /
            # assistant(tool_call) / tool(tool_call_response) turns. We can't
            # rely on the LLM child's own ``run.inputs`` because LangChain
            # often hands the model a pre-serialised prompt string, losing
            # the structured per-turn shape (see issue #172).
            if run_type in ("llm", "chat_model"):
                # Seed system/user messages from the agent's top-level inputs
                # on the first LLM call.
                if not content.get("seeded_initial"):
                    agent_run = self.run_map.get(str(agent_id))
                    if agent_run is not None:
                        seeded = _seed_initial_messages(getattr(agent_run, "inputs", None))
                        if seeded:
                            content["input_messages"].extend(seeded)
                    content["seeded_initial"] = True
                # Promote previous assistant turn into the history before this
                # LLM's own output becomes the new ``pending_assistant``.
                pending = content.get("pending_assistant")
                if pending:
                    # n>1 produces multiple choices; only one assistant turn
                    # actually fed back into the loop, so take the first.
                    content["input_messages"].append(_output_message_to_input(pending[0]))
                if run.outputs:
                    out_structured = _extract_structured_output_messages(run.outputs)
                    if out_structured:
                        content["pending_assistant"] = out_structured

            # Tool children: append a ``tool``-role message with a
            # ToolCallResponse part. The preceding pending assistant (which
            # requested this tool call) must be promoted into the history
            # FIRST so ordering is correct.
            if run_type == "tool":
                pending = content.get("pending_assistant")
                if pending:
                    content["input_messages"].append(_output_message_to_input(pending[0]))
                    content["pending_assistant"] = None
                tool_msg = _tool_run_to_input_message(run)
                if tool_msg is not None:
                    content["input_messages"].append(tool_msg)

            # NOTE: ``output_messages`` is populated from ``pending_assistant``
            # in ``_finalize_agent_span`` -- it represents the FINAL assistant
            # choice(s) only, per the GenAI semconv.

    def _find_agent_ancestor(self, run: Run) -> UUID | None:
        """Walk up the run tree to find the nearest agent ancestor run_id."""
        run_map = self.run_map
        current_id: UUID | None = run.parent_run_id
        while current_id:
            if current_id in self._agent_run_ids:
                return current_id
            parent_run = run_map.get(str(current_id))
            current_id = parent_run.parent_run_id if parent_run else None
        return None

    def _finalize_agent_span(self, span: Span, run: Run) -> None:
        """Apply aggregated content and status to an invoke_agent span."""
        # Set status
        if run.error is None or any(re.match(pattern, run.error) for pattern in IGNORED_EXCEPTION_PATTERNS):
            span.set_status(trace_api.StatusCode.OK)
        else:
            _apply_error_attributes(span, Error(message=run.error, type=Exception))

        span.set_attributes(dict(get_attributes_from_context()))

        with self._lock:
            content = self._agent_content.get(run.id) or {}

        # The final ``pending_assistant`` (the last LLM child's output) is the
        # agent's final response -- promote it to ``output_messages``.
        pending = content.get("pending_assistant")
        if pending:
            content["output_messages"] = pending

        # Defensive: if the incremental builder never seeded the initial
        # user/system turn (e.g. agent_run.inputs was not yet populated when
        # the first LLM child ended, or used an unusual shape), recover by
        # prepending them from agent_run.inputs at finalize-time. This is
        # idempotent: only happens when those roles are absent from the
        # already-built history.
        built = content.get("input_messages") or []
        if not any(getattr(m, "role", "") in ("user", "system") for m in built):
            seeded = _seed_initial_messages(getattr(run, "inputs", None))
            if seeded:
                content["input_messages"] = list(seeded) + list(built)

        # Set aggregated model
        if model := content.get("model"):
            span.set_attribute(GEN_AI_REQUEST_MODEL_KEY, model)

        if provider := content.get("provider"):
            span.set_attribute(GEN_AI_PROVIDER_NAME_KEY, provider)

        if (choice_count := content.get("request_choice_count")) and choice_count > 0:
            span.set_attribute(GEN_AI_REQUEST_CHOICE_COUNT_KEY, choice_count)

        if (input_tokens := content.get("input_tokens")) and input_tokens > 0:
            span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS_KEY, input_tokens)
        if (output_tokens := content.get("output_tokens")) and output_tokens > 0:
            span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS_KEY, output_tokens)

        # Set aggregated input/output messages only when content capture is enabled
        if _should_capture_content_on_spans():
            if tool_defs := content.get("tool_definitions"):
                span.set_attribute(GEN_AI_TOOL_DEFINITIONS_KEY, tool_defs)
            if msgs := content.get("input_messages"):
                span.set_attribute(
                    GEN_AI_INPUT_MESSAGES_KEY,
                    safe_json_dumps([asdict(m) for m in msgs]),
                )
            else:
                agent_msgs = _extract_agent_input_messages(run.inputs)
                if agent_msgs:
                    span.set_attribute(
                        GEN_AI_INPUT_MESSAGES_KEY,
                        safe_json_dumps([asdict(m) for m in agent_msgs]),
                    )

            if out_msgs := content.get("output_messages"):
                span.set_attribute(
                    GEN_AI_OUTPUT_MESSAGES_KEY,
                    safe_json_dumps([asdict(m) for m in out_msgs]),
                )
            else:
                agent_out_msgs = _extract_agent_output_messages(run.outputs)
                if agent_out_msgs:
                    span.set_attribute(
                        GEN_AI_OUTPUT_MESSAGES_KEY,
                        safe_json_dumps([asdict(m) for m in agent_out_msgs]),
                    )

        # Set metadata (session_id, etc.)
        span.set_attributes(dict(flatten(metadata(run))))


def get_attributes_from_context() -> Iterator[tuple[str, AttributeValue]]:
    for ctx_attr in CONTEXT_ATTRIBUTES:
        if (val := get_value(ctx_attr)) is not None:
            yield ctx_attr, cast(AttributeValue, val)


def _update_span(span: Span, run: Run) -> LLMInvocation | None:
    """Update a non-agent span with run data.

    Returns the ``LLMInvocation`` for LLM runs (used for event emission
    and future metrics), or ``None`` for other run types.
    """
    # If there is no error or if there is an agent control exception, set the span to OK
    if run.error is None or any(re.match(pattern, run.error) for pattern in IGNORED_EXCEPTION_PATTERNS):
        span.set_status(trace_api.StatusCode.OK)
    else:
        _apply_error_attributes(span, Error(message=run.error, type=Exception))

    span.set_attributes(dict(get_attributes_from_context()))

    run_type = run.run_type.lower()

    # --- LLM runs: use LLMInvocation + _apply_llm_finish_attributes ---
    if run_type in ("llm", "chat_model"):
        invocation = build_llm_invocation(run)
        _apply_llm_finish_attributes(span, invocation)
        # Fix "chat None" span name when model is unknown
        if invocation.request_model is None:
            span.update_name(CHAT_OPERATION_NAME)
        # Extras not covered by LLMInvocation
        span.set_attributes(
            dict(
                flatten(
                    chain(
                        prompts(run.inputs),
                        invocation_parameters(run),
                        function_calls(run.outputs),
                        metadata(run),
                    )
                )
            )
        )
        return invocation

    # --- Tool / chain / other runs ---
    span.set_attributes(
        dict(
            flatten(
                chain(
                    add_operation_type(run),
                    chain_node_messages(run.inputs, GEN_AI_INPUT_MESSAGES_KEY),
                    chain_node_messages(run.outputs, GEN_AI_OUTPUT_MESSAGES_KEY),
                    tools(run),
                    metadata(run),
                )
            )
        )
    )
    return None
