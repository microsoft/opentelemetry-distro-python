# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Data extraction functions for LangChain runs → OpenTelemetry span attributes."""

import datetime
import json
import logging
import math
from urllib.parse import urlparse
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
from enum import Enum
from threading import RLock
from typing import Any, Generic, TypeVar, cast

from langchain_core.messages import BaseMessage
from langchain_core.tracers.schemas import Run
from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_AGENT_DESCRIPTION,
    GEN_AI_AGENT_ID,
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OPERATION_NAME,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_OUTPUT_TYPE,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_CHOICE_COUNT,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_TOP_K,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_ID,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_DESCRIPTION,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GenAiOperationNameValues,
)
from opentelemetry.semconv.attributes.server_attributes import SERVER_ADDRESS, SERVER_PORT
from opentelemetry.util.genai.utils import (
    ContentCapturingMode,
    gen_ai_json_dumps,
    get_content_capturing_mode,
    is_experimental_mode,
)
from opentelemetry.util.genai.types import (
    InputMessage,
    LLMInvocation,
    OutputMessage,
    Text,
)

try:
    from opentelemetry.util.genai.types import ToolCallRequest as ToolCall  # type: ignore[attr-defined]  # >=0.4b0
except ImportError:
    from opentelemetry.util.genai.types import ToolCall  # type: ignore[no-redef,attr-defined]  # 0.3b0

try:
    from opentelemetry.util.genai.types import ToolCallResponse  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - older util-genai versions
    ToolCallResponse = None  # type: ignore[assignment,misc]

from opentelemetry.util.types import AttributeValue
from wrapt import ObjectProxy

try:
    from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
        GEN_AI_TOOL_DEFINITIONS,
    )
except ImportError:
    GEN_AI_TOOL_DEFINITIONS = "gen_ai.tool.definitions"  # type: ignore[misc]

try:
    from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as _gen_ai_attributes

    GEN_AI_USAGE_REASONING_OUTPUT_TOKENS = getattr(
        _gen_ai_attributes,
        "GEN_AI_USAGE_REASONING_OUTPUT_TOKENS",
        "gen_ai.usage.reasoning.output_tokens",
    )
except ImportError:
    GEN_AI_USAGE_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"  # type: ignore[misc]

try:
    from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
        GEN_AI_AGENT_VERSION,
    )
except ImportError:
    GEN_AI_AGENT_VERSION = "gen_ai.agent.version"  # type: ignore[misc]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---- Core utilities ----------------------------------------------------------


def _should_capture_content_on_spans(enable_sensitive_data: bool = False) -> bool:
    """Check if content should be captured on span attributes."""
    if enable_sensitive_data:
        return True
    if not is_experimental_mode():
        return False
    mode = get_content_capturing_mode()
    return mode in (ContentCapturingMode.SPAN_ONLY, ContentCapturingMode.SPAN_AND_EVENT)


def safe_json_dumps(obj: Any, **kwargs: Any) -> str:
    """JSON serializer that tolerates non-serializable LangChain objects.

    Prefer ``gen_ai_json_dumps`` for OTel-compliant attribute values.
    This wrapper adds ``default=str`` for LangChain data that may contain
    UUIDs, datetime objects, or other non-JSON-native types.
    """
    return str(gen_ai_json_dumps(obj, default=str, **kwargs))


def as_utc_nano(dt: datetime.datetime) -> int:
    return int(dt.astimezone(datetime.timezone.utc).timestamp() * 1_000_000_000)


KeyType = TypeVar("KeyType")
ValueType = TypeVar("ValueType")


# pylint: disable=too-many-branches, abstract-method, too-many-return-statements
# pylint: disable=broad-exception-caught
def get_first_value(mapping: Mapping[KeyType, ValueType], keys: Iterable[KeyType]) -> ValueType | None:
    if not hasattr(mapping, "get"):
        return None
    return next(
        (value for key in keys if (value := mapping.get(key)) is not None),
        None,
    )


def stop_on_exception(
    wrapped: Callable[..., Iterator[tuple[str, Any]]],
) -> Callable[..., Iterator[tuple[str, Any]]]:
    def wrapper(*args: Any, **kwargs: Any) -> Iterator[tuple[str, Any]]:
        try:
            yield from wrapped(*args, **kwargs)
        except Exception:
            logger.exception("Failed to get attribute.")

    return wrapper


@stop_on_exception
def flatten(key_values: Iterable[tuple[str, Any]]) -> Iterator[tuple[str, AttributeValue]]:
    for key, value in key_values:
        if value is None:
            continue
        if isinstance(value, Mapping):
            for sub_key, sub_value in flatten(value.items()):
                yield f"{key}.{sub_key}", sub_value
        elif isinstance(value, list) and any(isinstance(item, Mapping) for item in value):
            for index, sub_value in enumerate(value):
                if sub_value is None:
                    continue
                if isinstance(sub_value, Mapping):
                    for sub_key, flattened_sub_value in flatten(sub_value.items()):
                        yield f"{key}.{index}.{sub_key}", flattened_sub_value
                else:
                    if isinstance(sub_value, Enum):
                        sub_value = sub_value.value
                    yield f"{key}.{index}", sub_value
        else:
            if isinstance(value, Enum):
                value = value.value
            yield key, value


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class DictWithLock(ObjectProxy, Generic[K, V]):  # type: ignore
    def __init__(self, wrapped: dict[str, V] | None = None) -> None:
        super().__init__(wrapped or {})
        self._self_lock = RLock()

    def get(self, key: K) -> V | None:
        with self._self_lock:
            return cast(V | None, self.__wrapped__.get(key))

    def pop(self, key: K, *args: Any) -> V | None:
        with self._self_lock:
            return cast(V | None, self.__wrapped__.pop(key, *args))

    def __getitem__(self, key: K) -> V:
        with self._self_lock:
            return cast(V, super().__getitem__(key))

    def __setitem__(self, key: K, value: V) -> None:
        with self._self_lock:
            super().__setitem__(key, value)

    def __delitem__(self, key: K) -> None:
        with self._self_lock:
            super().__delitem__(key)


# ---- Semantic convention aliases (kept for readability) ----------------------

INVOKE_AGENT_OPERATION_NAME = GenAiOperationNameValues.INVOKE_AGENT.value
EXECUTE_TOOL_OPERATION_NAME = GenAiOperationNameValues.EXECUTE_TOOL.value
CHAT_OPERATION_NAME = GenAiOperationNameValues.CHAT.value

# Re-export canonical constants under short names for use by tracer.py
GEN_AI_OPERATION_NAME_KEY = GEN_AI_OPERATION_NAME
GEN_AI_REQUEST_MODEL_KEY = GEN_AI_REQUEST_MODEL
GEN_AI_RESPONSE_FINISH_REASONS_KEY = GEN_AI_RESPONSE_FINISH_REASONS
GEN_AI_RESPONSE_ID_KEY = GEN_AI_RESPONSE_ID
GEN_AI_RESPONSE_MODEL_KEY = GEN_AI_RESPONSE_MODEL
GEN_AI_USAGE_INPUT_TOKENS_KEY = GEN_AI_USAGE_INPUT_TOKENS
GEN_AI_USAGE_OUTPUT_TOKENS_KEY = GEN_AI_USAGE_OUTPUT_TOKENS
GEN_AI_USAGE_REASONING_OUTPUT_TOKENS_KEY = GEN_AI_USAGE_REASONING_OUTPUT_TOKENS
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY = GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY = GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS
GEN_AI_PROVIDER_NAME_KEY = GEN_AI_PROVIDER_NAME
GEN_AI_SYSTEM_INSTRUCTIONS_KEY = GEN_AI_SYSTEM_INSTRUCTIONS
GEN_AI_INPUT_MESSAGES_KEY = GEN_AI_INPUT_MESSAGES
GEN_AI_OUTPUT_MESSAGES_KEY = GEN_AI_OUTPUT_MESSAGES
GEN_AI_OUTPUT_TYPE_KEY = GEN_AI_OUTPUT_TYPE
GEN_AI_AGENT_NAME_KEY = GEN_AI_AGENT_NAME
GEN_AI_AGENT_ID_KEY = GEN_AI_AGENT_ID
GEN_AI_AGENT_DESCRIPTION_KEY = GEN_AI_AGENT_DESCRIPTION
GEN_AI_CONVERSATION_ID_KEY = GEN_AI_CONVERSATION_ID
GEN_AI_REQUEST_CHOICE_COUNT_KEY = GEN_AI_REQUEST_CHOICE_COUNT
GEN_AI_REQUEST_TOP_K_KEY = GEN_AI_REQUEST_TOP_K
SERVER_ADDRESS_KEY = SERVER_ADDRESS
SERVER_PORT_KEY = SERVER_PORT

# Tool execution constants
GEN_AI_TOOL_CALL_ID_KEY = GEN_AI_TOOL_CALL_ID
GEN_AI_TOOL_NAME_KEY = GEN_AI_TOOL_NAME
GEN_AI_TOOL_DESCRIPTION_KEY = GEN_AI_TOOL_DESCRIPTION
GEN_AI_TOOL_ARGS_KEY = GEN_AI_TOOL_CALL_ARGUMENTS
GEN_AI_TOOL_CALL_RESULT_KEY = GEN_AI_TOOL_CALL_RESULT
GEN_AI_TOOL_TYPE_KEY = GEN_AI_TOOL_TYPE
GEN_AI_TOOL_DEFINITIONS_KEY = GEN_AI_TOOL_DEFINITIONS
GEN_AI_AGENT_VERSION_KEY = GEN_AI_AGENT_VERSION


# ---- Internal helpers --------------------------------------------------------

IGNORED_EXCEPTION_PATTERNS = [
    r"^Command\(",
    r"^ParentCommand\(",
]

LANGCHAIN_SESSION_ID = "session_id"
LANGCHAIN_CONVERSATION_ID = "conversation_id"
LANGCHAIN_THREAD_ID = "thread_id"


@stop_on_exception
def prompts(
    inputs: Mapping[str, Any] | None,
    enable_sensitive_data: bool = False,
) -> Iterator[tuple[str, list[str]]]:
    if not _should_capture_content_on_spans(enable_sensitive_data):
        return
    if not inputs:
        return
    if not isinstance(inputs, Mapping):
        return
    if p := inputs.get("prompts"):
        yield GEN_AI_SYSTEM_INSTRUCTIONS_KEY, p


@stop_on_exception
def input_messages(
    inputs: Mapping[str, Any] | None,
) -> Iterator[tuple[str, str]]:
    if not inputs:
        return
    if not isinstance(inputs, Mapping):
        return
    contents: list[str] = []
    multiple_messages = inputs.get("messages")
    if multiple_messages and isinstance(multiple_messages, Iterable):
        # LangChain can provide either:
        # - nested format: {"messages": [[...]]}
        # - flat format: {"messages": [...]} (list of message objects)
        if isinstance(multiple_messages, list) and multiple_messages:
            first_item = multiple_messages[0]
            if isinstance(first_item, list):
                message_items: list[Any] = first_item
            else:
                message_items = multiple_messages
        else:
            first_messages = next(iter(multiple_messages), None)
            if isinstance(first_messages, list):
                message_items = first_messages
            elif first_messages is not None:
                message_items = [first_messages]
            else:
                message_items = []

        for message_data in message_items:
            if isinstance(message_data, BaseMessage):
                if hasattr(message_data, "content") and message_data.content:
                    contents.append(str(message_data.content))
            elif hasattr(message_data, "get"):
                if content := message_data.get("content"):
                    contents.append(str(content))
                elif kwargs := message_data.get("kwargs"):
                    if hasattr(kwargs, "get") and (content := kwargs.get("content")):
                        contents.append(str(content))
            elif isinstance(message_data, Sequence) and len(message_data) == 2:
                _role, content = message_data
                contents.append(str(content))

    # Some providers flatten chat input to prompts for chat_model/llm runs.
    if not contents and (prompt_values := inputs.get("prompts")):
        if isinstance(prompt_values, list):
            contents.extend(str(p) for p in prompt_values if p)
        elif isinstance(prompt_values, str):
            contents.append(prompt_values)

    if contents:
        yield GEN_AI_INPUT_MESSAGES_KEY, safe_json_dumps(contents)


@stop_on_exception
def metadata(run: Run) -> Iterator[tuple[str, str]]:
    if not run.extra or not (meta := run.extra.get("metadata")):
        return
    if not isinstance(meta, Mapping):
        return
    if session_id := (
        meta.get(LANGCHAIN_SESSION_ID) or meta.get(LANGCHAIN_CONVERSATION_ID) or meta.get(LANGCHAIN_THREAD_ID)
    ):
        yield GEN_AI_CONVERSATION_ID_KEY, session_id


@stop_on_exception
def output_messages(
    outputs: Mapping[str, Any] | None,
) -> Iterator[tuple[str, str]]:
    if not outputs:
        return
    if not isinstance(outputs, Mapping):
        return
    output_type = outputs.get("type")
    if output_type and output_type.lower() == "llmresult":
        llm_output = outputs.get("llm_output")
        if llm_output and hasattr(llm_output, "get"):
            response_id = llm_output.get("id")
            if response_id:
                yield GEN_AI_RESPONSE_ID_KEY, response_id
    if not (multiple_generations := outputs.get("generations")):
        return
    if not isinstance(multiple_generations, Iterable):
        return

    if isinstance(multiple_generations, list) and multiple_generations:
        first_item = multiple_generations[0]
        if isinstance(first_item, list):
            generation_items: list[Any] = first_item
        elif isinstance(first_item, Mapping):
            generation_items = multiple_generations
        else:
            generation_items = []
    else:
        first_generations = next(iter(multiple_generations), None)
        if first_generations is None:
            return
        if isinstance(first_generations, list):
            generation_items = first_generations
        elif isinstance(first_generations, Mapping):
            generation_items = [first_generations]
        else:
            return

    contents: list[str] = []
    for generation in generation_items:
        if not isinstance(generation, Mapping):
            continue
        if message_data := generation.get("message"):
            if isinstance(message_data, BaseMessage):
                if hasattr(message_data, "content") and message_data.content:
                    contents.append(str(message_data.content))
            elif hasattr(message_data, "get"):
                if content := message_data.get("content"):
                    contents.append(str(content))
                elif kwargs := message_data.get("kwargs"):
                    if hasattr(kwargs, "get") and (content := kwargs.get("content")):
                        contents.append(str(content))
    if contents:
        yield GEN_AI_OUTPUT_MESSAGES_KEY, safe_json_dumps(contents)


@stop_on_exception
def invocation_parameters(run: Run) -> Iterator[tuple[str, AttributeValue]]:  # pylint: disable=too-many-statements
    if run.run_type.lower() not in ("llm", "chat_model"):
        return
    if not (extra := run.extra):
        return
    if not isinstance(extra, Mapping):
        return
    if inv_params := extra.get("invocation_params"):
        if not isinstance(inv_params, Mapping):
            return
        param_sources: list[Mapping[str, Any]] = [inv_params]
        if isinstance(model_kwargs := inv_params.get("model_kwargs"), Mapping):
            param_sources.append(model_kwargs)
            if isinstance(model_kwargs_extra_body := model_kwargs.get("extra_body"), Mapping):
                param_sources.append(model_kwargs_extra_body)
            if isinstance(model_kwargs_kwargs := model_kwargs.get("kwargs"), Mapping):
                param_sources.append(model_kwargs_kwargs)
        if isinstance(inv_extra_body := inv_params.get("extra_body"), Mapping):
            param_sources.append(inv_extra_body)
        if isinstance(inv_kwargs := inv_params.get("kwargs"), Mapping):
            param_sources.append(inv_kwargs)
        if isinstance(extra_model_kwargs := extra.get("model_kwargs"), Mapping):
            param_sources.append(extra_model_kwargs)
            if isinstance(extra_model_kwargs_extra_body := extra_model_kwargs.get("extra_body"), Mapping):
                param_sources.append(extra_model_kwargs_extra_body)
            if isinstance(extra_model_kwargs_kwargs := extra_model_kwargs.get("kwargs"), Mapping):
                param_sources.append(extra_model_kwargs_kwargs)

        def _first_param(*keys: str) -> Any:
            for source in param_sources:
                if (value := get_first_value(source, keys)) is not None:
                    return value
            return None

        tool_defs = []
        for source_key in ("tools", "functions"):
            for source in param_sources:
                tool_list = source.get(source_key, [])
                if isinstance(tool_list, list):
                    tool_defs.extend(tool_list)
        if tool_defs:
            yield GEN_AI_TOOL_DEFINITIONS_KEY, safe_json_dumps(tool_defs)

        # gen_ai.request.choice_count (OpenAI/Anthropic "n")
        choice_count: int | None = None
        for choice_key in ("n", "num_choices", "candidate_count"):
            if (n_val := _first_param(choice_key)) is not None:
                try:
                    n_int = int(n_val)
                except (ValueError, TypeError):
                    pass
                else:
                    if n_int > 0:
                        choice_count = n_int
                    break
        # Some wrappers (notably OpenAI Responses) may not preserve ``n`` in
        # invocation_params. In that case infer count from returned choices.
        if choice_count is None and isinstance(run.outputs, Mapping):
            generations = run.outputs.get("generations")
            if isinstance(generations, list) and generations:
                first_item = generations[0]
                if isinstance(first_item, list):
                    inferred = len(first_item)
                elif isinstance(first_item, Mapping):
                    inferred = len(generations)
                else:
                    inferred = 0
                if inferred > 0:
                    choice_count = inferred
        if choice_count is not None:
            yield GEN_AI_REQUEST_CHOICE_COUNT_KEY, choice_count

        # gen_ai.request.top_k
        if (top_k_val := _first_param("top_k")) is not None:
            try:
                yield GEN_AI_REQUEST_TOP_K_KEY, float(top_k_val)
            except (ValueError, TypeError):
                pass

        # gen_ai.openai.request.response_format + gen_ai.output.type
        if (response_format := _first_param("response_format")) is not None:
            out_type = _output_type_from_response_format(response_format)
            if out_type:
                yield GEN_AI_OUTPUT_TYPE_KEY, out_type


def _usage_mapping(token_usage: Any) -> Mapping[str, Any] | None:
    if isinstance(token_usage, Mapping):
        return token_usage
    if callable(model_dump := getattr(token_usage, "model_dump", None)):
        try:
            dumped = model_dump(exclude_none=True)
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    if callable(dict_method := getattr(token_usage, "dict", None)):
        try:
            dumped = dict_method(exclude_none=True)
        except TypeError:
            dumped = dict_method()
        if isinstance(dumped, Mapping):
            return dumped
    extracted: dict[str, Any] = {}
    for attr_name in (
        "prompt_tokens",
        "input_tokens",
        "prompt_token_count",
        "completion_tokens",
        "output_tokens",
        "candidates_token_count",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = getattr(token_usage, attr_name, None)
        if value is not None:
            extracted[attr_name] = value
    for attr_name in (
        "input_token_details",
        "prompt_tokens_details",
        "output_token_details",
        "completion_tokens_details",
    ):
        value = getattr(token_usage, attr_name, None)
        if value is not None and (nested := _usage_mapping(value)) is not None:
            extracted[attr_name] = nested
    return extracted or None


def _output_type_from_response_format(response_format: Any) -> str | None:
    """Map OpenAI/LangChain ``response_format`` to ``gen_ai.output.type``."""
    if isinstance(response_format, str):
        rf = response_format.lower()
        if rf in ("json", "json_object", "json_schema"):
            return "json"
        if rf == "text":
            return "text"
        return None
    if isinstance(response_format, Mapping):
        rf_type = response_format.get("type")
        if isinstance(rf_type, str):
            rf_type_l = rf_type.lower()
            if rf_type_l in ("json_object", "json_schema"):
                return "json"
            if rf_type_l == "text":
                return "text"
    return None


@stop_on_exception
def llm_provider(extra: Mapping[str, Any] | None) -> Iterator[tuple[str, str]]:
    if not extra:
        return
    if (meta := extra.get("metadata")) and (ls_provider := meta.get("ls_provider")):
        yield GEN_AI_PROVIDER_NAME_KEY, ls_provider.lower()
        return
    inv_params = extra.get("invocation_params")
    if not isinstance(inv_params, Mapping):
        return
    if inv_params.get("use_responses_api"):
        yield GEN_AI_PROVIDER_NAME_KEY, "openai"
        return
    base_url = inv_params.get("base_url")
    if isinstance(base_url, str) and "openai" in base_url.lower():
        yield GEN_AI_PROVIDER_NAME_KEY, "openai"


@stop_on_exception
def model_name(
    outputs: Mapping[str, Any] | None,
    extra: Mapping[str, Any] | None,
) -> Iterator[tuple[str, str]]:
    if outputs and hasattr(outputs, "get") and (llm_output := outputs.get("llm_output")) and hasattr(llm_output, "get"):
        for key in ("model_name", "model"):
            if name := str(llm_output.get(key) or "").strip():
                yield GEN_AI_REQUEST_MODEL_KEY, name
                return
    if not extra:
        return
    if not isinstance(extra, Mapping):
        return
    if (
        (meta := extra.get("metadata"))
        and hasattr(meta, "get")
        and (ls_model_name := str(meta.get("ls_model_name") or "").strip())
    ):
        yield GEN_AI_REQUEST_MODEL_KEY, ls_model_name
        return
    if not (inv_params := extra.get("invocation_params")):
        return
    for key in ("model_name", "model"):
        if name := inv_params.get(key):
            yield GEN_AI_REQUEST_MODEL_KEY, name
            return


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _as_usage_mapping(raw_usage: Any) -> Mapping[str, Any] | None:
    if isinstance(raw_usage, Mapping):
        return raw_usage

    if callable(model_dump := getattr(raw_usage, "model_dump", None)):
        try:
            dumped = model_dump(exclude_none=True)
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped

    if callable(dict_method := getattr(raw_usage, "dict", None)):
        try:
            dumped = dict_method(exclude_none=True)
        except TypeError:
            dumped = dict_method()
        if isinstance(dumped, Mapping):
            return dumped

    usage: dict[str, Any] = {}
    for scalar_key in (
        "prompt_tokens",
        "input_tokens",
        "prompt_token_count",
        "completion_tokens",
        "output_tokens",
        "candidates_token_count",
        "total_tokens",
        "total_token_count",
    ):
        scalar_value = getattr(raw_usage, scalar_key, None)
        if scalar_value is not None:
            usage[scalar_key] = scalar_value

    for nested_key in (
        "input_token_details",
        "output_token_details",
        "prompt_tokens_details",
        "completion_tokens_details",
    ):
        nested_value = getattr(raw_usage, nested_key, None)
        if nested_value is None:
            continue
        if nested_mapping := _as_usage_mapping(nested_value):
            usage[nested_key] = nested_mapping

    return usage or None


def _normalized_token_usage(outputs: Mapping[str, Any] | None) -> dict[str, int]:
    if not (raw_token_usage := _parse_token_usage(outputs)):
        return {}
    # Normalize to Mapping so get_first_value works even when the usage object
    # is a non-Mapping (e.g. SimpleNamespace or Pydantic model).
    token_usage = _as_usage_mapping(raw_token_usage) or {}
    input_count = _as_non_negative_int(
        get_first_value(token_usage, ("prompt_tokens", "input_tokens", "prompt_token_count"))
    )
    output_count = _as_non_negative_int(
        get_first_value(token_usage, ("completion_tokens", "output_tokens", "candidates_token_count"))
    )
    total_count = _as_non_negative_int(get_first_value(token_usage, ("total_tokens", "total_token_count")))
    if total_count is None and input_count is not None and output_count is not None:
        total_count = input_count + output_count

    usage: dict[str, int] = {}
    if input_count is not None:
        usage["input_tokens"] = input_count
    if output_count is not None:
        usage["output_tokens"] = output_count
    if total_count is not None:
        # Kept internal for parity/future metrics, not emitted as a semconv span attribute.
        usage["total_tokens"] = total_count
    return usage


@stop_on_exception
def token_counts(outputs: Mapping[str, Any] | None) -> Iterator[tuple[str, int]]:
    usage = _normalized_token_usage(outputs)
    if (input_tokens := usage.get("input_tokens")) is not None:
        yield GEN_AI_USAGE_INPUT_TOKENS_KEY, input_tokens
    if (output_tokens := usage.get("output_tokens")) is not None:
        yield GEN_AI_USAGE_OUTPUT_TOKENS_KEY, output_tokens
    if usage_mapping := _as_usage_mapping(_parse_token_usage(outputs)):
        for attribute_name, token_count in _extra_usage_attributes(usage_mapping):
            yield attribute_name, token_count


def _iter_generation_mappings(outputs: Mapping[str, Any] | None) -> Iterator[Mapping[str, Any]]:
    """Yield generation mappings from both nested and flat generations payloads."""
    if not isinstance(outputs, Mapping):
        return
    generations = outputs.get("generations")
    if not isinstance(generations, Iterable):
        return

    if isinstance(generations, list):
        if not generations:
            return
        first_item = generations[0]
        # Nested shape: generations = [[{...}, {...}], ...]
        if isinstance(first_item, list):
            for generation in first_item:
                if isinstance(generation, Mapping):
                    yield generation
            return
        # Flat shape: generations = [{...}, {...}]
        if isinstance(first_item, Mapping):
            for generation in generations:
                if isinstance(generation, Mapping):
                    yield generation
            return

    # Generic iterable fallback
    first_generations = next(iter(generations), None)
    if first_generations is None:
        return
    if isinstance(first_generations, Mapping):
        yield first_generations
        return
    if isinstance(first_generations, Iterable):
        for generation in first_generations:
            if isinstance(generation, Mapping):
                yield generation
        return


def _extra_usage_attributes(token_usage: Mapping[str, Any]) -> Iterator[tuple[str, int]]:
    # Cache token accounting (gen_ai.usage.cache_*_input_tokens).
    # Sources:
    #   - OpenAI: token_usage["prompt_tokens_details"]["cached_tokens"]
    #   - Anthropic: top-level "cache_read_input_tokens" / "cache_creation_input_tokens"
    #   - langchain_core UsageMetadata: token_usage["input_token_details"]["cache_read"|"cache_creation"]
    cache_read: int | None = None
    cache_creation: int | None = None
    if isinstance(input_details := token_usage.get("input_token_details"), Mapping):
        cache_read = _as_non_negative_int(input_details.get("cache_read"))
        cache_creation = _as_non_negative_int(input_details.get("cache_creation"))
    if cache_read is None and isinstance(prompt_details := token_usage.get("prompt_tokens_details"), Mapping):
        cache_read = _as_non_negative_int(prompt_details.get("cached_tokens"))
    if cache_read is None:
        cache_read = _as_non_negative_int(token_usage.get("cache_read_input_tokens"))
    if cache_creation is None:
        cache_creation = _as_non_negative_int(token_usage.get("cache_creation_input_tokens"))
    if cache_read is not None:
        yield GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY, cache_read
    if cache_creation is not None:
        yield GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY, cache_creation

    reasoning_output: int | None = None
    if isinstance(output_details := token_usage.get("output_token_details"), Mapping):
        reasoning_output = _as_non_negative_int(output_details.get("reasoning"))
    if reasoning_output is None and isinstance(
        completion_details := token_usage.get("completion_tokens_details"), Mapping
    ):
        reasoning_output = _as_non_negative_int(completion_details.get("reasoning_tokens"))
    if reasoning_output is not None:
        yield GEN_AI_USAGE_REASONING_OUTPUT_TOKENS_KEY, reasoning_output


def _iter_generation_response_metadata(outputs: Mapping[str, Any] | None) -> Iterator[Mapping[str, Any]]:
    """Yield ``response_metadata`` / ``generation_info`` mappings on each generation."""
    for generation in _iter_generation_mappings(outputs):
        gen_info = generation.get("generation_info")
        if isinstance(gen_info, Mapping):
            yield gen_info
        message_data = generation.get("message")
        if isinstance(message_data, BaseMessage):
            meta = getattr(message_data, "response_metadata", None)
        elif isinstance(message_data, Mapping):
            meta = message_data.get("response_metadata")
            if meta is None and isinstance(kwargs := message_data.get("kwargs"), Mapping):
                meta = kwargs.get("response_metadata")
        else:
            meta = None
        if isinstance(meta, Mapping):
            yield meta


def _parse_token_usage(outputs: Mapping[str, Any] | None) -> Any:
    if (
        outputs
        and hasattr(outputs, "get")
        and (llm_output := outputs.get("llm_output"))
        and hasattr(llm_output, "get")
        and (token_usage := get_first_value(llm_output, ("token_usage", "usage")))
    ):
        return token_usage
    if outputs and hasattr(outputs, "get") and (top_usage := outputs.get("usage")):
        return top_usage
    # Fallback for code paths (e.g. OpenAI Responses API in langchain-openai) where
    # ``llm_output["token_usage"]`` is not populated and usage lives on each
    # generation's ``message.usage_metadata`` (langchain_core ``UsageMetadata``) or
    # in ``message.response_metadata.token_usage``.
    if not isinstance(outputs, Mapping):
        return None
    for generation in _iter_generation_mappings(outputs):
        usage: Any = None

        gen_info = generation.get("generation_info")
        if isinstance(gen_info, Mapping):
            usage = get_first_value(gen_info, ("token_usage", "usage"))
            if usage is None:
                usage = gen_info

        message_data = generation.get("message")
        if usage is None:
            if isinstance(message_data, BaseMessage):
                usage = getattr(message_data, "usage_metadata", None)
                if not usage:
                    resp_meta = getattr(message_data, "response_metadata", None)
                    if isinstance(resp_meta, Mapping):
                        usage = get_first_value(resp_meta, ("token_usage", "usage"))
            elif isinstance(message_data, Mapping):
                usage = message_data.get("usage_metadata")
                if not usage and isinstance(kwargs := message_data.get("kwargs"), Mapping):
                    usage = kwargs.get("usage_metadata")
                    if not usage and isinstance(resp_meta := kwargs.get("response_metadata"), Mapping):
                        usage = get_first_value(resp_meta, ("token_usage", "usage"))
                if not usage and isinstance(resp_meta := message_data.get("response_metadata"), Mapping):
                    usage = get_first_value(resp_meta, ("token_usage", "usage"))

        if usage_mapping := _as_usage_mapping(usage):
            return usage_mapping
    return None


@stop_on_exception
def function_calls(outputs: Mapping[str, Any] | None, enable_sensitive_data: bool = False) -> Iterator[tuple[str, str]]:
    if not outputs:
        return
    if not isinstance(outputs, Mapping):
        return
    try:
        fc = deepcopy(outputs["generations"][0][0]["message"]["kwargs"]["additional_kwargs"]["function_call"])
    except Exception:
        return
    if not isinstance(fc, dict):
        return
    yield GEN_AI_TOOL_TYPE_KEY, "function"
    name = fc.get("name")
    if isinstance(name, str):
        yield GEN_AI_TOOL_NAME_KEY, name
    desc = fc.get("description")
    if isinstance(desc, str):
        yield GEN_AI_TOOL_DESCRIPTION_KEY, desc
    call_id = fc.get("id")
    if isinstance(call_id, str):
        yield GEN_AI_TOOL_CALL_ID_KEY, call_id
    if _should_capture_content_on_spans(enable_sensitive_data):
        args = fc.get("arguments")
        if args is not None:
            if isinstance(args, str):
                try:
                    args_json = safe_json_dumps(json.loads(args))
                except Exception:
                    args_json = safe_json_dumps(args)
            else:
                args_json = safe_json_dumps(args)
            yield GEN_AI_TOOL_ARGS_KEY, args_json
        result = fc.get("result")
        if result is not None:
            yield GEN_AI_TOOL_CALL_RESULT_KEY, safe_json_dumps(result)


@stop_on_exception
def tools(run: Run, enable_sensitive_data: bool = False) -> Iterator[tuple[str, str]]:
    if run.run_type.lower() != "tool":
        return
    if not (serialized := run.serialized):
        return
    if not isinstance(serialized, Mapping):
        return
    yield GEN_AI_TOOL_TYPE_KEY, "function"
    if name := serialized.get("name"):
        yield GEN_AI_TOOL_NAME_KEY, name
    if description := serialized.get("description"):
        yield GEN_AI_TOOL_DESCRIPTION_KEY, description
    if run.extra and hasattr(run.extra, "get"):
        if tool_call_id := run.extra.get("tool_call_id"):
            yield GEN_AI_TOOL_CALL_ID_KEY, tool_call_id
    if _should_capture_content_on_spans(enable_sensitive_data):
        if run.inputs and hasattr(run.inputs, "get"):
            _sentinel = object()
            input_val = run.inputs.get("input", _sentinel)
            if input_val is _sentinel:
                input_val = run.inputs
            if isinstance(input_val, str):
                yield GEN_AI_TOOL_ARGS_KEY, input_val
            else:
                yield GEN_AI_TOOL_ARGS_KEY, safe_json_dumps(input_val)
        if run.outputs and hasattr(run.outputs, "get"):
            _sentinel = object()
            result = run.outputs.get("output", _sentinel)
            if result is not _sentinel:
                if isinstance(result, BaseMessage):
                    result_content: str = str(result.content) if hasattr(result, "content") else str(result)
                elif hasattr(result, "content"):
                    result_content = str(result.content)
                elif isinstance(result, str):
                    result_content = result
                else:
                    result_content = safe_json_dumps(result)
                yield GEN_AI_TOOL_CALL_RESULT_KEY, result_content


def chain_node_messages(
    data: Mapping[str, Any] | None,
    attr_key: str,
    enable_sensitive_data: bool = False,
) -> Iterator[tuple[str, str]]:
    """Extract messages from a LangGraph chain node's inputs or outputs.

    Chain nodes typically store messages as ``{"messages": [BaseMessage, ...]}``.
    """
    if not _should_capture_content_on_spans(enable_sensitive_data):
        return
    if not data or not isinstance(data, Mapping):
        return
    messages = data.get("messages")
    if not messages or not isinstance(messages, list):
        return
    contents: list[str] = []
    for msg in messages:
        c = _langchain_content(msg)
        if c:
            role = _langchain_role(msg)
            contents.append(f"{role}: {c}")
    if contents:
        yield attr_key, safe_json_dumps(contents)


def add_operation_type(run: Run) -> Iterator[tuple[str, str]]:
    run_type = run.run_type.lower()
    if run_type in ("llm", "chat_model"):
        yield GEN_AI_OPERATION_NAME_KEY, CHAT_OPERATION_NAME
    elif run_type == "tool":
        yield GEN_AI_OPERATION_NAME_KEY, EXECUTE_TOOL_OPERATION_NAME


def _normalize_server_address(raw: Any) -> str | None:
    """Normalize URL-like endpoint values to host names for server.address."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"//{text}")
    return parsed.hostname or text.rstrip("/")


def build_llm_invocation(run: Run) -> LLMInvocation:  # pylint: disable=too-many-statements
    """Build an ``LLMInvocation`` from a LangChain ``Run`` for LLM-type spans.

    This bridges LangChain's run data model to the canonical OTel GenAI
    data model so that ``_apply_llm_finish_attributes`` can be used.
    """
    inv = LLMInvocation()

    # --- Model name ---
    for _, val in model_name(run.outputs, run.extra):
        inv.request_model = val
        break

    # --- Provider ---
    for _, val in llm_provider(run.extra):
        inv.provider = val
        break

    # --- Request parameters from invocation_params ---
    if run.extra and isinstance(run.extra, Mapping):
        inv_params = run.extra.get("invocation_params") or {}
        if isinstance(inv_params, Mapping):
            params_sources: list[Mapping[str, Any]] = [inv_params]
            model_kwargs = inv_params.get("model_kwargs")
            if isinstance(model_kwargs, Mapping):
                params_sources.append(model_kwargs)

            def _first_param(*keys: str) -> Any:
                for source in params_sources:
                    value = get_first_value(source, keys)
                    if value is not None:
                        return value
                return None

            try:
                if (temp := _first_param("temperature")) is not None:
                    val = float(temp)
                    if math.isfinite(val):
                        inv.temperature = val
            except (ValueError, TypeError):
                pass
            try:
                if (tp := _first_param("top_p")) is not None:
                    val = float(tp)
                    if math.isfinite(val):
                        inv.top_p = val
            except (ValueError, TypeError):
                pass
            try:
                if (mt := _first_param("max_tokens", "max_output_tokens")) is not None:
                    inv.max_tokens = int(mt)
            except (ValueError, TypeError):
                pass
            try:
                if (fp := _first_param("frequency_penalty")) is not None:
                    val = float(fp)
                    if math.isfinite(val):
                        inv.frequency_penalty = val
            except (ValueError, TypeError):
                pass
            try:
                if (pp := _first_param("presence_penalty")) is not None:
                    val = float(pp)
                    if math.isfinite(val):
                        inv.presence_penalty = val
            except (ValueError, TypeError):
                pass
            try:
                if (seed_val := _first_param("seed")) is not None:
                    inv.seed = int(seed_val)
            except (ValueError, TypeError):
                pass
            stop = _first_param("stop", "stop_sequences")
            if stop is not None:
                if isinstance(stop, str):
                    inv.stop_sequences = [stop]
                elif isinstance(stop, list):
                    inv.stop_sequences = [str(s) for s in stop]

            for key in (
                "base_url",
                "api_base",
                "openai_api_base",
                "azure_endpoint",
                "endpoint",
                "endpoint_url",
                "service_url",
            ):
                if (addr := _first_param(key)) is not None:
                    if normalized_addr := _normalize_server_address(addr):
                        inv.server_address = normalized_addr
                        break

        if not inv.server_address and isinstance(meta := run.extra.get("metadata"), Mapping):
            for key in ("ls_server_address", "server.address"):
                if (addr := meta.get(key)) is not None:
                    if normalized_addr := _normalize_server_address(addr):
                        inv.server_address = normalized_addr
                        break

    # --- Response model name (from llm_output) ---
    if run.outputs and isinstance(run.outputs, Mapping):
        llm_output = run.outputs.get("llm_output")
        if llm_output and hasattr(llm_output, "get"):
            for key in ("model_name", "model"):
                if resp_model := llm_output.get(key):
                    inv.response_model_name = str(resp_model)
                    break

    # --- Token counts ---
    for key, val in token_counts(run.outputs):
        if key == GEN_AI_USAGE_INPUT_TOKENS_KEY:
            inv.input_tokens = val
        elif key == GEN_AI_USAGE_OUTPUT_TOKENS_KEY:
            inv.output_tokens = val
        elif key in (
            GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY,
            GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY,
            GEN_AI_USAGE_REASONING_OUTPUT_TOKENS_KEY,
        ):
            inv.attributes[key] = val

    # --- Response ID ---
    if run.outputs and isinstance(run.outputs, Mapping):
        llm_output = run.outputs.get("llm_output")
        if llm_output and hasattr(llm_output, "get"):
            if resp_id := llm_output.get("id"):
                inv.response_id = str(resp_id)

    # ``llm_output`` is only populated for the OpenAI client path patched by
    # ``opentelemetry-instrumentation-openai-v2``. ``AzureChatOpenAI`` and
    # streaming responses use langchain-openai's own httpx pipeline and only
    # surface ``response.model`` / ``response.id`` on each generation's
    # ``response_metadata`` (or ``generation_info``). Fall back to those.
    if not inv.response_model_name or not inv.response_id:
        for meta in _iter_generation_response_metadata(run.outputs):
            if not inv.response_model_name:
                if resp_model := get_first_value(meta, ("model_name", "model")):
                    inv.response_model_name = str(resp_model)
            if not inv.response_id:
                if resp_id := meta.get("id"):
                    inv.response_id = str(resp_id)
            if inv.response_model_name and inv.response_id:
                break

    # --- Structured messages ---
    inv.system_instruction = _extract_system_instruction(run.inputs)  # type: ignore[assignment]
    inv.input_messages = _extract_structured_input_messages(run.inputs)
    inv.output_messages = _extract_structured_output_messages(run.outputs)

    return inv


def _langchain_role(message: Any) -> str:
    """Extract role from a LangChain message (BaseMessage or dict)."""
    if isinstance(message, BaseMessage):
        msg_type = str(getattr(message, "type", "unknown"))
        return "assistant" if msg_type == "ai" else msg_type
    if hasattr(message, "get"):
        if role := message.get("role"):
            return str(role)
        # LangChain serializes messages with the "lc envelope":
        # {"lc": 1, "type": "constructor", "id": [..., "AIMessage"], "kwargs": {...}}
        # The "constructor" string is a serialization marker, not the role —
        # fall through to id-field parsing in that case.
        msg_type = message.get("type")
        if msg_type and msg_type != "constructor":
            return "assistant" if msg_type == "ai" else str(msg_type)
        # Fallback: parse role from serialized id field (e.g. ["langchain", "schema", "HumanMessage"])
        if id_field := message.get("id"):
            if isinstance(id_field, list) and len(id_field) > 0:
                type_name = id_field[-1]
                if "Human" in type_name:
                    return "user"
                if "AI" in type_name or "Assistant" in type_name:
                    return "assistant"
                if "System" in type_name:
                    return "system"
                if "Tool" in type_name:
                    return "tool"
    return "unknown"


def _flatten_lc_content_blocks(content: Any) -> str | None:
    """Normalize a LangChain message ``content`` value to a plain text string.

    LangChain/LangGraph ``AIMessage.content`` may be either a plain string or a
    list of content-block dicts (e.g. ``[{"type": "text", "text": "...",
    "phase": "final_answer", "id": "..."}]``).  The GenAI semantic-conventions
    ``TextPart.content`` field must be a plain string, so we concatenate the
    ``text`` of every ``type=="text"`` block (joined with ``\n``) and drop the
    rest.  Non-text blocks (e.g. ``tool_use`` / ``tool_result``) are surfaced
    elsewhere as typed parts, so it is correct to omit them from the text.

    Returns ``None`` when there is no meaningful text content.
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, Mapping):
                block_type = block.get("type")
                # Accept both spec-typed text blocks and untyped {"text": "..."} entries.
                if block_type in (None, "text"):
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        chunks.append(text)
            elif isinstance(block, str) and block:
                chunks.append(block)
        if chunks:
            return "\n".join(chunks)
        return None
    return str(content) or None


def _langchain_content(message: Any) -> str | None:
    """Extract text content from a LangChain message."""
    if isinstance(message, BaseMessage):
        return _flatten_lc_content_blocks(getattr(message, "content", None))
    if hasattr(message, "get"):
        if (c := message.get("content")) is not None:
            flat = _flatten_lc_content_blocks(c)
            if flat is not None:
                return flat
        if kwargs := message.get("kwargs"):
            if hasattr(kwargs, "get") and (c := kwargs.get("content")) is not None:
                return _flatten_lc_content_blocks(c)
    return None


def _lc_content_blocks(message: Any) -> list[Any] | None:
    """Return the raw ``content`` value of a LangChain message if it is a list
    of content blocks, otherwise ``None``."""
    raw: Any = None
    if isinstance(message, BaseMessage):
        raw = getattr(message, "content", None)
    elif hasattr(message, "get"):
        raw = message.get("content")
        if raw is None:
            kwargs = message.get("kwargs") or {}
            if hasattr(kwargs, "get"):
                raw = kwargs.get("content")
    return raw if isinstance(raw, list) else None


def _langchain_tool_calls(message: Any) -> list[ToolCall]:
    """Extract tool calls from a LangChain message into OTel ToolCall parts."""
    calls: list[ToolCall] = []
    raw_calls = None
    if isinstance(message, BaseMessage):
        raw_calls = getattr(message, "tool_calls", None)
        if not raw_calls:
            raw_calls = getattr(message, "additional_kwargs", {}).get("tool_calls")
    elif hasattr(message, "get"):
        raw_calls = message.get("tool_calls")
        if not raw_calls:
            kwargs = message.get("kwargs") or {}
            raw_calls = kwargs.get("tool_calls")
            if not raw_calls:
                additional = kwargs.get("additional_kwargs") or {}
                raw_calls = additional.get("tool_calls")
    if not raw_calls or not isinstance(raw_calls, list):
        raw_calls = []
    else:
        # Copy before mutation so we never alter the caller's message object.
        raw_calls = list(raw_calls)
    # Anthropic / LangGraph models often emit tool calls only as
    # ``{"type": "tool_use", "id": "...", "name": "...", "input": {...}}``
    # entries inside a list-shaped ``content`` field, with
    # ``message.tool_calls`` and ``additional_kwargs["tool_calls"]`` empty.
    # Without this loop those calls would never reach ``parts``: the
    # ``tool_calls`` lookup above returns nothing, and ``_langchain_content``
    # (via ``_flatten_lc_content_blocks``) only keeps ``type=="text"`` blocks
    # and discards the rest.  Harvest them here so they surface as spec
    # ``ToolCallRequest`` parts.
    content_blocks = _lc_content_blocks(message)
    if content_blocks:
        for block in content_blocks:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") != "tool_use":
                continue
            raw_calls.append(
                {
                    "name": block.get("name"),
                    "id": block.get("id"),
                    "args": block.get("input"),
                }
            )
    if not raw_calls:
        return calls
    for tc in raw_calls:
        if not isinstance(tc, Mapping):
            continue
        name = tc.get("name") or ""
        fn = tc.get("function")
        if isinstance(fn, Mapping):
            name = fn.get("name") or name
            args = fn.get("arguments")
        else:
            args = tc.get("args")
        if args is not None and not isinstance(args, str):
            args = safe_json_dumps(args)
        calls.append(ToolCall(arguments=args or "", name=name, id=tc.get("id")))
    return calls


def _langchain_tool_responses(message: Any) -> list[Any]:
    """Extract a ``ToolCallResponse`` part from a LangChain ``ToolMessage``.

    Returns a list (possibly empty) of ``ToolCallResponse`` parts. Falls back
    to an empty list when the optional dataclass isn't available in the
    installed ``opentelemetry-util-genai`` version.
    """
    if ToolCallResponse is None:
        return []
    tool_call_id: Any = None
    response: Any = None
    if isinstance(message, BaseMessage):
        msg_type = str(getattr(message, "type", ""))
        if msg_type != "tool":
            return []
        tool_call_id = getattr(message, "tool_call_id", None)
        response = getattr(message, "content", None)
    elif hasattr(message, "get"):
        # Serialized form (dict). Could be {"type": "tool", ...} or lc envelope.
        msg_type = message.get("type")
        kwargs = message.get("kwargs") if hasattr(message.get("kwargs"), "get") else None
        id_field = message.get("id")
        is_tool = msg_type == "tool"
        if not is_tool and isinstance(id_field, list) and id_field and "Tool" in str(id_field[-1]):
            is_tool = True
        if not is_tool and message.get("role") == "tool":
            is_tool = True
        if not is_tool:
            return []
        tool_call_id = message.get("tool_call_id")
        if tool_call_id is None and kwargs is not None:
            tool_call_id = kwargs.get("tool_call_id")
        response = message.get("content")
        if response is None and kwargs is not None:
            response = kwargs.get("content")
    else:
        return []
    if response is None and tool_call_id is None:
        return []
    if response is not None and not isinstance(response, str):
        response = safe_json_dumps(response)
    return [ToolCallResponse(response=response or "", id=tool_call_id)]


def _extract_system_instruction(inputs: Mapping[str, Any] | None) -> list[Text]:
    """Extract system instruction / prompts as structured Text parts."""
    if not inputs or not isinstance(inputs, Mapping):
        return []
    if p := inputs.get("prompts"):
        if isinstance(p, list):
            return [Text(content=str(item)) for item in p if item]
        if isinstance(p, str):
            return [Text(content=p)]
    return []


def _extract_structured_input_messages(
    inputs: Mapping[str, Any] | None,
) -> list[InputMessage]:
    """Convert LangChain input messages to OTel ``InputMessage`` list."""
    if not inputs or not isinstance(inputs, Mapping):
        return []
    multiple_messages = inputs.get("messages")
    if multiple_messages and isinstance(multiple_messages, Iterable):
        first_messages = next(iter(multiple_messages), None)
        if first_messages is not None:
            # Normalise to a list
            if not isinstance(first_messages, list):
                first_messages = [first_messages]
            results: list[InputMessage] = []
            for msg in first_messages:
                role = _normalize_role(_langchain_role(msg))
                parts: list[Any] = []
                tool_responses = _langchain_tool_responses(msg)
                if tool_responses:
                    # tool-role messages carry their result as a ToolCallResponse
                    # part rather than as plain Text content.
                    parts.extend(tool_responses)
                else:
                    content = _langchain_content(msg)
                    if content:
                        parts.append(Text(content=content))
                parts.extend(_langchain_tool_calls(msg))
                if parts:
                    results.append(InputMessage(role=role, parts=parts))
            if results:
                return results

    # Fallback: LLM runs use "prompts" (list of formatted prompt strings)
    p = inputs.get("prompts")
    if isinstance(p, list):
        results = []
        for item in p:
            if item:
                results.append(InputMessage(role="user", parts=[Text(content=str(item))]))
        if results:
            return results
    elif isinstance(p, str) and p:
        return [InputMessage(role="user", parts=[Text(content=p)])]

    return []


def _extract_structured_output_messages(
    outputs: Mapping[str, Any] | None,
) -> list[OutputMessage]:
    """Convert LangChain output generations to OTel ``OutputMessage`` list."""
    if not outputs or not isinstance(outputs, Mapping):
        return []
    multiple_generations = outputs.get("generations")
    if not multiple_generations or not isinstance(multiple_generations, Iterable):
        return []
    first_generations = next(iter(multiple_generations), None)
    if not first_generations or not isinstance(first_generations, Iterable):
        return []
    results: list[OutputMessage] = []
    for generation in first_generations:
        if not isinstance(generation, Mapping):
            continue
        message_data = generation.get("message")
        if message_data is None:
            # Fallback: generation may have text directly
            if text := generation.get("text"):
                results.append(OutputMessage(role="assistant", parts=[Text(content=str(text))], finish_reason="stop"))
            continue
        role = _normalize_role(_langchain_role(message_data))
        parts: list[Any] = []
        content = _langchain_content(message_data)
        if content:
            parts.append(Text(content=content))
        parts.extend(_langchain_tool_calls(message_data))
        # Try to get finish_reason from generation_info
        finish_reason = "stop"
        gen_info = generation.get("generation_info")
        if isinstance(gen_info, Mapping):
            finish_reason = gen_info.get("finish_reason") or "stop"
        if parts:
            results.append(OutputMessage(role=role, parts=parts, finish_reason=finish_reason))
    return results


# Mapping from LangChain-native roles to OTel GenAI semconv roles.
_LANGCHAIN_ROLE_TO_OTEL: dict[str, str] = {
    "human": "user",
    "ai": "assistant",
}


def _normalize_role(role: str) -> str:
    """Normalize a LangChain role to OTel GenAI semconv role."""
    return _LANGCHAIN_ROLE_TO_OTEL.get(role, role)


def _extract_agent_input_messages(
    inputs: Mapping[str, Any] | None,
) -> list[InputMessage]:
    """Convert agent-level input messages to OTel ``InputMessage`` list.

    Agent runs store messages as a flat list under the ``messages`` key,
    unlike LLM runs which nest them as list-of-lists.
    """
    if not inputs or not isinstance(inputs, Mapping):
        return []
    messages = inputs.get("messages")
    if not messages or not isinstance(messages, list):
        return []
    # Handle potential nested lists
    if len(messages) > 0 and isinstance(messages[0], list):
        messages = messages[0]
    results: list[InputMessage] = []
    for msg in messages:
        # LangChain accepts a ``(role, content)`` 2-tuple shorthand for
        # messages (e.g. ``[("human", "hi")]``); normalise it to a dict so
        # the role/content extractors see a familiar shape.
        if isinstance(msg, tuple) and len(msg) == 2:
            msg = {"role": msg[0], "content": msg[1]}
        role = _normalize_role(_langchain_role(msg))
        parts: list[Any] = []
        # Tool-role messages in a pre-populated ReAct history must surface
        # as ``tool_call_response`` parts, not plain text.
        tool_responses = _langchain_tool_responses(msg)
        if tool_responses:
            parts.extend(tool_responses)
        else:
            content = _langchain_content(msg)
            if content:
                parts.append(Text(content=content))
            parts.extend(_langchain_tool_calls(msg))
        if parts:
            results.append(InputMessage(role=role, parts=parts))
    return results


def _extract_agent_output_messages(
    outputs: Mapping[str, Any] | None,
) -> list[OutputMessage]:
    """Convert agent-level output messages to OTel ``OutputMessage`` list.

    Agent runs store output as a flat messages list.  Extracts the last
    assistant/AI message as the agent output.
    """
    if not outputs or not isinstance(outputs, Mapping):
        return []
    messages = outputs.get("messages")
    if not messages or not isinstance(messages, list):
        return []
    # Handle potential nested lists
    if len(messages) > 0 and isinstance(messages[0], list):
        messages = messages[0]
    results: list[OutputMessage] = []
    for msg in reversed(messages):
        role = _normalize_role(_langchain_role(msg))
        if role and role.lower() in ("assistant",):
            parts: list[Any] = []
            content = _langchain_content(msg)
            if content and isinstance(content, str) and content.strip():
                parts.append(Text(content=content))
            parts.extend(_langchain_tool_calls(msg))
            if parts:
                results.append(OutputMessage(role=role, parts=parts, finish_reason="stop"))
                break
    return results


# ---- Agent input-history builders (issue #172) -------------------------------


def _is_structured_output_run(run: Run) -> bool:
    """Return True if this LLM/chat run came from ``with_structured_output``."""
    extra = run.extra
    if not isinstance(extra, Mapping):
        return False
    for container_key in ("options", "invocation_params", "metadata"):
        container = extra.get(container_key)
        if isinstance(container, Mapping):
            if container.get("ls_structured_output_format") is not None:
                return True
            if container.get("structured_output_format") is not None:
                return True
    return False


def _seed_initial_messages(inputs: Mapping[str, Any] | None) -> list[InputMessage]:
    """Return the initial system/user messages from an agent's top-level inputs.

    Used to seed ``gen_ai.input.messages`` on the wrapper invoke_agent span
    with the user prompt(s) before any LLM/tool turns are appended.
    """
    seeded = _extract_agent_input_messages(inputs)
    if seeded:
        return seeded
    structured = _extract_structured_input_messages(inputs)
    return structured or []


def _extract_tool_call_id(tool_run: Run) -> str | None:
    """Best-effort lookup of ``tool_call_id`` for a LangChain tool run."""
    sources: list[Any] = []
    if tool_run.inputs is not None:
        sources.append(tool_run.inputs)
    if tool_run.extra is not None:
        sources.append(tool_run.extra)
        if isinstance(tool_run.extra, Mapping):
            meta = tool_run.extra.get("metadata")
            if meta is not None:
                sources.append(meta)
    for src in sources:
        if isinstance(src, Mapping):
            for key in ("tool_call_id", "id"):
                if val := src.get(key):
                    return str(val)
    return None


def _tool_run_to_input_message(tool_run: Run) -> InputMessage | None:
    """Build a ``tool``-role InputMessage with a ``ToolCallResponse`` part."""
    if ToolCallResponse is None:
        return None
    outputs = tool_run.outputs
    output: Any = None
    if isinstance(outputs, Mapping):
        sentinel = object()
        output = outputs.get("output", sentinel)
        if output is sentinel:
            output = outputs
    elif outputs is not None:
        output = outputs
    if output is None:
        return None
    # If the tool returned a LangChain ``ToolMessage`` (or any BaseMessage),
    # use its ``content`` (and prefer its ``tool_call_id`` when present).
    # Otherwise ``str(ToolMessage)`` yields an unhelpful repr like
    # ``content='...' name='...' tool_call_id='...'``.
    tool_call_id = _extract_tool_call_id(tool_run)
    if isinstance(output, BaseMessage):
        if not tool_call_id:
            tool_call_id = getattr(output, "tool_call_id", None)
        msg_content = getattr(output, "content", None)
        output = msg_content if msg_content is not None else ""
    if not isinstance(output, str):
        output = safe_json_dumps(output)
    return InputMessage(
        role="tool",
        parts=[ToolCallResponse(response=output, id=tool_call_id)],
    )


def _output_message_to_input(out_msg: OutputMessage) -> InputMessage:
    """Convert an ``OutputMessage`` (assistant) to an ``InputMessage`` so it
    can be appended to ``gen_ai.input.messages`` as a history turn."""
    return InputMessage(role=out_msg.role, parts=list(out_msg.parts))


@stop_on_exception
def invoke_agent_input_message(
    inputs: Mapping[str, Any] | None,
) -> Iterator[tuple[str, str]]:
    if not inputs:
        return
    if not isinstance(inputs, Mapping):
        return
    messages = inputs.get("messages")
    if not messages:
        return
    if isinstance(messages, list) and len(messages) > 0:
        first_item = messages[0]
        if isinstance(first_item, list):
            messages = first_item
    if isinstance(messages, list):
        for message in messages:
            role = _langchain_role(message)
            if role and role.lower() in ("human", "user"):
                content = _langchain_content(message)
                if content:
                    yield GEN_AI_INPUT_MESSAGES_KEY, content
                    return
        if len(messages) > 0:
            content = _langchain_content(messages[0])
            if content:
                yield GEN_AI_INPUT_MESSAGES_KEY, content


@stop_on_exception
def invoke_agent_output_message(
    outputs: Mapping[str, Any] | None,
) -> Iterator[tuple[str, str]]:
    if not outputs:
        return
    if not isinstance(outputs, Mapping):
        return
    messages = outputs.get("messages")
    if not messages:
        return
    if isinstance(messages, list) and len(messages) > 0:
        first_item = messages[0]
        if isinstance(first_item, list):
            messages = first_item
    if isinstance(messages, list):
        for message in reversed(messages):
            role = _langchain_role(message)
            if role and role.lower() in ("ai", "assistant"):
                content = _langchain_content(message)
                if content and isinstance(content, str) and content.strip():
                    yield GEN_AI_OUTPUT_MESSAGES_KEY, content
                    return


@stop_on_exception
def extract_agent_metadata(run: Run) -> Iterator[tuple[str, str]]:
    """Extract agent name and description from run metadata or serialized data."""
    # From run metadata
    if run.extra and isinstance(run.extra, dict):
        meta = run.extra.get("metadata")
        if isinstance(meta, dict):
            if name := meta.get("agent_name"):
                yield GEN_AI_AGENT_NAME_KEY, name
            if agent_id := meta.get("agent_id"):
                yield GEN_AI_AGENT_ID_KEY, agent_id
            if desc := meta.get("agent_description"):
                yield GEN_AI_AGENT_DESCRIPTION_KEY, desc
            return
    # From serialized graph
    if run.serialized and isinstance(run.serialized, dict):
        if name := run.serialized.get("name"):
            if name != "LangGraph":
                yield GEN_AI_AGENT_NAME_KEY, name


@stop_on_exception
def extract_session_info(run: Run) -> Iterator[tuple[str, str]]:
    """Extract conversation ID from run metadata as gen_ai.conversation.id."""
    if not run.extra or not isinstance(run.extra, dict):
        return
    meta = run.extra.get("metadata")
    if not isinstance(meta, dict):
        return
    for key in (LANGCHAIN_SESSION_ID, LANGCHAIN_CONVERSATION_ID, LANGCHAIN_THREAD_ID):
        if sid := meta.get(key):
            yield GEN_AI_CONVERSATION_ID_KEY, sid
            break
