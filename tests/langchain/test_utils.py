# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import datetime
import json
from enum import Enum
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("langchain_core")

from microsoft.opentelemetry._genai._langchain._utils import (  # noqa: E402
    DictWithLock,
    CHAT_OPERATION_NAME,
    EXECUTE_TOOL_OPERATION_NAME,
    GEN_AI_AGENT_DESCRIPTION_KEY,
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
    GEN_AI_OUTPUT_TYPE_KEY,
    GEN_AI_PROVIDER_NAME_KEY,
    GEN_AI_REQUEST_CHOICE_COUNT_KEY,
    GEN_AI_REQUEST_MODEL_KEY,
    GEN_AI_REQUEST_TOP_K_KEY,
    GEN_AI_SYSTEM_INSTRUCTIONS_KEY,
    GEN_AI_TOOL_ARGS_KEY,
    GEN_AI_TOOL_CALL_ID_KEY,
    GEN_AI_TOOL_CALL_RESULT_KEY,
    GEN_AI_TOOL_DEFINITIONS_KEY,
    GEN_AI_TOOL_DESCRIPTION_KEY,
    GEN_AI_TOOL_NAME_KEY,
    GEN_AI_TOOL_TYPE_KEY,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY,
    GEN_AI_USAGE_INPUT_TOKENS_KEY,
    GEN_AI_USAGE_OUTPUT_TOKENS_KEY,
    GEN_AI_USAGE_REASONING_OUTPUT_TOKENS_KEY,
    add_operation_type,
    as_utc_nano,
    build_llm_invocation,
    chain_node_messages,
    extract_agent_metadata,
    extract_session_info,
    flatten,
    function_calls,
    get_first_value,
    input_messages,
    invocation_parameters,
    invoke_agent_input_message,
    invoke_agent_output_message,
    llm_provider,
    metadata,
    model_name,
    output_messages,
    prompts,
    safe_json_dumps,
    stop_on_exception,
    token_counts,
    _extract_agent_input_messages,
    _extract_agent_output_messages,
    tools,
)


def _make_run(**kwargs):
    """Create a minimal mock Run with sensible defaults."""
    run = MagicMock()
    run.id = kwargs.get("id", "run-1")
    run.name = kwargs.get("name", "test_run")
    run.run_type = kwargs.get("run_type", "chain")
    run.inputs = kwargs.get("inputs")
    run.outputs = kwargs.get("outputs")
    run.extra = kwargs.get("extra")
    run.serialized = kwargs.get("serialized")
    run.error = kwargs.get("error")
    run.parent_run_id = kwargs.get("parent_run_id")
    run.start_time = kwargs.get("start_time", datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc))
    run.end_time = kwargs.get("end_time", datetime.datetime(2024, 1, 1, second=1, tzinfo=datetime.timezone.utc))
    return run


# ---- Core utilities ----------------------------------------------------------


class TestSafeJsonDumps(TestCase):
    def test_serializes_dict(self):
        result = safe_json_dumps({"key": "value"})
        self.assertEqual(json.loads(result), {"key": "value"})

    def test_handles_non_serializable_types(self):
        import uuid

        obj = {"id": uuid.UUID("12345678-1234-5678-1234-567812345678")}
        result = safe_json_dumps(obj)
        self.assertIn("12345678-1234-5678-1234-567812345678", result)

    def test_handles_datetime(self):
        obj = {"ts": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)}
        result = safe_json_dumps(obj)
        self.assertIn("2024", result)


class TestAsUtcNano(TestCase):
    def test_epoch_returns_zero(self):
        dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        self.assertEqual(as_utc_nano(dt), 0)

    def test_known_timestamp(self):
        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        expected = int(dt.timestamp() * 1_000_000_000)
        self.assertEqual(as_utc_nano(dt), expected)


class TestGetFirstValue(TestCase):
    def test_returns_first_match(self):
        mapping = {"a": 1, "b": 2, "c": 3}
        self.assertEqual(get_first_value(mapping, ["x", "b", "c"]), 2)

    def test_returns_none_when_no_match(self):
        mapping = {"a": 1}
        self.assertIsNone(get_first_value(mapping, ["x", "y"]))

    def test_skips_none_values(self):
        mapping = {"a": None, "b": 2}
        self.assertEqual(get_first_value(mapping, ["a", "b"]), 2)

    def test_handles_non_mapping(self):
        self.assertIsNone(get_first_value("not a mapping", ["a"]))


class TestStopOnException(TestCase):
    def test_yields_normally(self):
        @stop_on_exception
        def gen():
            yield ("k", "v")

        self.assertEqual(list(gen()), [("k", "v")])

    def test_catches_exception(self):
        @stop_on_exception
        def gen():
            raise ValueError("boom")
            yield ("k", "v")  # noqa: unreachable

        self.assertEqual(list(gen()), [])


class TestFlatten(TestCase):
    def test_simple_key_value(self):
        result = list(flatten([("key", "value")]))
        self.assertEqual(result, [("key", "value")])

    def test_nested_dict(self):
        result = list(flatten([("parent", {"child": "value"})]))
        self.assertEqual(result, [("parent.child", "value")])

    def test_skips_none(self):
        result = list(flatten([("key", None)]))
        self.assertEqual(result, [])

    def test_enum_value(self):
        class Color(Enum):
            RED = "red"

        result = list(flatten([("color", Color.RED)]))
        self.assertEqual(result, [("color", "red")])

    def test_list_of_dicts(self):
        data = [("items", [{"a": 1}, {"b": 2}])]
        result = list(flatten(data))
        self.assertEqual(result, [("items.0.a", 1), ("items.1.b", 2)])


class TestDictWithLock(TestCase):
    def test_get_set(self):
        d = DictWithLock()
        d["key"] = "value"
        self.assertEqual(d.get("key"), "value")

    def test_get_missing(self):
        d = DictWithLock()
        self.assertIsNone(d.get("missing"))

    def test_pop(self):
        d = DictWithLock({"key": "value"})
        self.assertEqual(d.pop("key"), "value")
        self.assertIsNone(d.get("key"))

    def test_del(self):
        d = DictWithLock({"key": "value"})
        del d["key"]
        self.assertIsNone(d.get("key"))


# ---- Data extractors ---------------------------------------------------------


class TestPrompts(TestCase):
    def test_extracts_prompts(self):
        inputs = {"prompts": ["System prompt here"]}
        result = list(prompts(inputs))
        self.assertEqual(result, [(GEN_AI_SYSTEM_INSTRUCTIONS_KEY, ["System prompt here"])])

    def test_returns_empty_on_none(self):
        self.assertEqual(list(prompts(None)), [])

    def test_returns_empty_on_no_prompts(self):
        self.assertEqual(list(prompts({"other": "data"})), [])


class TestInputMessages(TestCase):
    def test_extracts_from_basemessage(self):
        msg = MagicMock(spec=["content"])
        msg.content = "Hello"
        # Ensure isinstance(msg, BaseMessage) doesn't match for mock
        # Use dict-style messages instead for reliable testing
        inputs = {"messages": [[{"content": "Hello"}]]}
        result = list(input_messages(inputs))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], GEN_AI_INPUT_MESSAGES_KEY)

    def test_returns_empty_on_none(self):
        self.assertEqual(list(input_messages(None)), [])

    def test_returns_empty_on_no_messages(self):
        self.assertEqual(list(input_messages({"other": "data"})), [])

    def test_extracts_from_dict_messages(self):
        inputs = {"messages": [[{"content": "Hi"}, {"content": "There"}]]}
        result = list(input_messages(inputs))
        self.assertEqual(len(result), 1)
        parsed = json.loads(result[0][1])
        self.assertEqual(parsed, ["Hi", "There"])

    def test_extracts_from_flat_message_list(self):
        inputs = {"messages": [{"content": "Hi"}, {"content": "There"}]}
        result = list(input_messages(inputs))
        self.assertEqual(len(result), 1)
        parsed = json.loads(result[0][1])
        self.assertEqual(parsed, ["Hi", "There"])

    def test_extracts_from_prompts_fallback(self):
        inputs = {"prompts": ["System prompt", "User prompt"]}
        result = list(input_messages(inputs))
        self.assertEqual(len(result), 1)
        parsed = json.loads(result[0][1])
        self.assertEqual(parsed, ["System prompt", "User prompt"])


class TestMetadata(TestCase):
    def test_extracts_session_id(self):
        run = _make_run(extra={"metadata": {"session_id": "sess-123"}})
        result = list(metadata(run))
        self.assertEqual(result, [(GEN_AI_CONVERSATION_ID_KEY, "sess-123")])

    def test_extracts_conversation_id(self):
        run = _make_run(extra={"metadata": {"conversation_id": "conv-456"}})
        result = list(metadata(run))
        self.assertEqual(result, [(GEN_AI_CONVERSATION_ID_KEY, "conv-456")])

    def test_extracts_thread_id(self):
        run = _make_run(extra={"metadata": {"thread_id": "thread-789"}})
        result = list(metadata(run))
        self.assertEqual(result, [(GEN_AI_CONVERSATION_ID_KEY, "thread-789")])

    def test_returns_empty_on_no_extra(self):
        run = _make_run(extra=None)
        self.assertEqual(list(metadata(run)), [])


class TestOutputMessages(TestCase):
    def test_extracts_from_generations(self):
        outputs = {
            "generations": [[{"message": {"content": "Response", "role": "assistant"}}]],
        }
        result = list(output_messages(outputs))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], GEN_AI_OUTPUT_MESSAGES_KEY)

    def test_returns_empty_on_none(self):
        self.assertEqual(list(output_messages(None)), [])

    def test_extracts_response_id(self):
        outputs = {
            "type": "LLMResult",
            "llm_output": {"id": "resp-123"},
            "generations": [[{"message": {"content": "Hi"}}]],
        }
        result = dict(output_messages(outputs))
        self.assertIn("resp-123", str(result))

    def test_extracts_from_flat_generations(self):
        outputs = {
            "generations": [{"message": {"content": "Response", "role": "assistant"}}],
        }
        result = list(output_messages(outputs))
        self.assertEqual(len(result), 1)
        parsed = json.loads(result[0][1])
        self.assertEqual(parsed, ["Response"])


class TestLlmProvider(TestCase):
    def test_extracts_provider(self):
        extra = {"metadata": {"ls_provider": "OpenAI"}}
        result = list(llm_provider(extra))
        self.assertEqual(result, [(GEN_AI_PROVIDER_NAME_KEY, "openai")])

    def test_returns_empty_on_none(self):
        self.assertEqual(list(llm_provider(None)), [])

    def test_falls_back_to_openai_for_responses_api(self):
        extra = {"invocation_params": {"use_responses_api": True, "model": "gpt-4.1"}}
        result = list(llm_provider(extra))
        self.assertEqual(result, [(GEN_AI_PROVIDER_NAME_KEY, "openai")])

    def test_falls_back_to_openai_from_base_url(self):
        extra = {"invocation_params": {"base_url": "https://example.test/openai/v1/"}}
        result = list(llm_provider(extra))
        self.assertEqual(result, [(GEN_AI_PROVIDER_NAME_KEY, "openai")])


class TestModelName(TestCase):
    def test_from_llm_output(self):
        outputs = {"llm_output": {"model_name": "gpt-4"}}
        result = list(model_name(outputs, None))
        self.assertEqual(result, [(GEN_AI_REQUEST_MODEL_KEY, "gpt-4")])

    def test_from_metadata(self):
        extra = {"metadata": {"ls_model_name": "gpt-3.5-turbo"}}
        result = list(model_name(None, extra))
        self.assertEqual(result, [(GEN_AI_REQUEST_MODEL_KEY, "gpt-3.5-turbo")])

    def test_from_invocation_params(self):
        extra = {"invocation_params": {"model_name": "claude-3"}}
        result = list(model_name(None, extra))
        self.assertEqual(result, [(GEN_AI_REQUEST_MODEL_KEY, "claude-3")])

    def test_returns_empty_on_none(self):
        self.assertEqual(list(model_name(None, None)), [])


class TestTokenCounts(TestCase):
    def test_extracts_token_counts(self):
        outputs = {
            "llm_output": {
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                }
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 10)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 20)

    def test_ignores_reasoning_token_metadata(self):
        outputs = {
            "llm_output": {
                "token_usage": {
                    "completion_tokens_details": {"reasoning_tokens": 7},
                    "input_tokens": 10,
                    "output_token_details": {"reasoning": 5},
                    "output_tokens": 20,
                }
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 10)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 20)
        self.assertEqual(result[GEN_AI_USAGE_REASONING_OUTPUT_TOKENS_KEY], 5)

    def test_returns_empty_on_none(self):
        self.assertEqual(list(token_counts(None)), [])

    def test_extracts_from_llm_output_usage_alias(self):
        outputs = {
            "llm_output": {
                "usage": {
                    "input_tokens": 4,
                    "output_tokens": 9,
                }
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 4)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 9)

    def test_extracts_from_message_usage_metadata(self):
        outputs = {
            "generations": [[{"message": {"usage_metadata": {"prompt_tokens": 12, "completion_tokens": 7}}}]],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 12)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 7)

    def test_extracts_from_flat_generations_usage_metadata(self):
        outputs = {
            "generations": [{"message": {"usage_metadata": {"input_tokens": 5, "output_tokens": 2}}}],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 5)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 2)

    def test_extracts_from_flat_generations_kwargs_usage_metadata(self):
        outputs = {
            "generations": [
                {
                    "message": {
                        "kwargs": {
                            "usage_metadata": {
                                "input_tokens": 12,
                                "output_tokens": 4,
                            }
                        }
                    }
                }
            ],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 12)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 4)

    def test_extracts_from_message_response_metadata_token_usage(self):
        outputs = {
            "generations": [
                [
                    {
                        "message": {
                            "kwargs": {
                                "response_metadata": {
                                    "token_usage": {
                                        "prompt_token_count": 16,
                                        "candidates_token_count": 5,
                                    }
                                }
                            }
                        }
                    }
                ]
            ],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 16)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 5)

    def test_extracts_from_generation_info_usage(self):
        outputs = {
            "generations": [
                [
                    {
                        "generation_info": {
                            "usage": {
                                "prompt_tokens": 20,
                                "completion_tokens": 3,
                            }
                        }
                    }
                ]
            ],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 20)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 3)

    def test_extracts_from_object_usage(self):
        outputs = {
            "llm_output": {
                "usage": SimpleNamespace(
                    prompt_tokens=6,
                    completion_tokens=8,
                )
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 6)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 8)


class TestTokenCountsCache(TestCase):
    def test_extracts_cache_read_and_creation_from_input_token_details(self):
        outputs = {
            "llm_output": {
                "token_usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "input_token_details": {"cache_read": 80, "cache_creation": 10},
                }
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY], 80)
        self.assertEqual(result[GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY], 10)

    def test_extracts_cache_read_from_openai_prompt_tokens_details(self):
        outputs = {
            "llm_output": {
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 75},
                }
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY], 75)
        self.assertNotIn(GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY, result)

    def test_extracts_anthropic_top_level_cache_keys(self):
        outputs = {
            "llm_output": {
                "token_usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 60,
                    "cache_creation_input_tokens": 40,
                }
            }
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY], 60)
        self.assertEqual(result[GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS_KEY], 40)


class TestTokenCountsResponsesApi(TestCase):
    """OpenAI Responses API path: tokens live on per-generation message.usage_metadata.

    ``llm_output["token_usage"]`` is absent / empty; the langchain-openai
    Responses API output_version puts usage on the AIMessage instead.
    """

    def test_extracts_from_serialized_message_usage_metadata(self):
        outputs = {
            "llm_output": {},  # empty / no token_usage
            "generations": [
                [
                    {
                        "message": {
                            "kwargs": {
                                "usage_metadata": {
                                    "input_tokens": 115,
                                    "output_tokens": 2584,
                                    "total_tokens": 2699,
                                }
                            }
                        }
                    }
                ]
            ],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 115)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 2584)

    def test_extracts_from_message_usage_metadata_top_level(self):
        outputs = {
            "llm_output": None,
            "generations": [
                [
                    {
                        "message": {
                            "usage_metadata": {
                                "input_tokens": 7,
                                "output_tokens": 11,
                            }
                        }
                    }
                ]
            ],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 7)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 11)

    def test_extracts_from_basemessage_usage_metadata(self):
        from langchain_core.messages import AIMessage

        msg = AIMessage(
            content="hi",
            usage_metadata={"input_tokens": 50, "output_tokens": 8, "total_tokens": 58},
        )
        outputs = {
            "llm_output": {},
            "generations": [[{"message": msg}]],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 50)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 8)

    def test_extracts_cache_from_responses_api_input_token_details(self):
        outputs = {
            "llm_output": {},
            "generations": [
                [
                    {
                        "message": {
                            "kwargs": {
                                "usage_metadata": {
                                    "input_tokens": 100,
                                    "output_tokens": 20,
                                    "input_token_details": {"cache_read": 80},
                                }
                            }
                        }
                    }
                ]
            ],
        }
        result = dict(token_counts(outputs))
        self.assertEqual(result[GEN_AI_USAGE_INPUT_TOKENS_KEY], 100)
        self.assertEqual(result[GEN_AI_USAGE_OUTPUT_TOKENS_KEY], 20)
        self.assertEqual(result[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS_KEY], 80)


class TestInvocationParameters(TestCase):
    def test_extracts_tools(self):
        run = _make_run(
            run_type="llm",
            extra={"invocation_params": {"tools": [{"name": "get_weather"}]}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(len(result), 1)
        self.assertIn("get_weather", result[GEN_AI_TOOL_DEFINITIONS_KEY])

    def test_extracts_tools_for_chat_model(self):
        run = _make_run(
            run_type="chat_model",
            extra={"invocation_params": {"functions": [{"name": "get_weather"}]}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(len(result), 1)
        self.assertIn("get_weather", result[GEN_AI_TOOL_DEFINITIONS_KEY])

    def test_skips_non_llm(self):
        run = _make_run(run_type="chain", extra={"invocation_params": {"tools": []}})
        self.assertEqual(list(invocation_parameters(run)), [])

    def test_extracts_choice_count(self):
        run = _make_run(
            run_type="llm",
            extra={"invocation_params": {"n": 3}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 3)

    def test_extracts_choice_count_when_one(self):
        run = _make_run(
            run_type="llm",
            extra={"invocation_params": {"n": 1}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 1)

    def test_extracts_choice_count_from_model_kwargs(self):
        run = _make_run(
            run_type="llm",
            extra={"invocation_params": {"model_kwargs": {"n": 1}}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 1)

    def test_extracts_choice_count_from_invocation_kwargs(self):
        run = _make_run(
            run_type="chat_model",
            extra={"invocation_params": {"kwargs": {"n": 2}, "use_responses_api": True}},
            outputs={"generations": [{"message": {"content": "only one"}}]},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 2)

    def test_extracts_choice_count_from_model_kwargs_extra_body(self):
        run = _make_run(
            run_type="chat_model",
            extra={
                "invocation_params": {
                    "model_kwargs": {"extra_body": {"n": 2}},
                    "use_responses_api": True,
                }
            },
            outputs={"generations": [{"message": {"content": "only one"}}]},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 2)

    def test_infers_choice_count_from_flat_generations_when_n_missing(self):
        run = _make_run(
            run_type="chat_model",
            extra={"invocation_params": {"model": "gpt-4.1", "use_responses_api": True}},
            outputs={"generations": [{"message": {"content": "a"}}, {"message": {"content": "b"}}]},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 2)

    def test_infers_choice_count_from_nested_generations_when_n_missing(self):
        run = _make_run(
            run_type="llm",
            extra={"invocation_params": {"model": "gpt-4.1", "use_responses_api": True}},
            outputs={"generations": [[{"message": {"content": "a"}}, {"message": {"content": "b"}}]]},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_CHOICE_COUNT_KEY], 2)

    def test_extracts_top_k(self):
        run = _make_run(
            run_type="chat_model",
            extra={"invocation_params": {"top_k": 40}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_REQUEST_TOP_K_KEY], 40.0)

    def test_extracts_response_format_json_object(self):
        run = _make_run(
            run_type="chat_model",
            extra={"invocation_params": {"response_format": {"type": "json_object"}}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_OUTPUT_TYPE_KEY], "json")

    def test_extracts_response_format_text_string(self):
        run = _make_run(
            run_type="chat_model",
            extra={"invocation_params": {"response_format": "text"}},
        )
        result = dict(invocation_parameters(run))
        self.assertEqual(result[GEN_AI_OUTPUT_TYPE_KEY], "text")


class TestFunctionCalls(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._utils._should_capture_content_on_spans", return_value=False)
    def test_extracts_function_call(self, _mock_capture):
        outputs = {
            "generations": [
                [
                    {
                        "message": {
                            "kwargs": {
                                "additional_kwargs": {
                                    "function_call": {
                                        "name": "get_weather",
                                        "arguments": '{"city": "NYC"}',
                                    }
                                }
                            }
                        }
                    }
                ]
            ]
        }
        result = dict(function_calls(outputs))
        self.assertEqual(result[GEN_AI_TOOL_NAME_KEY], "get_weather")
        self.assertEqual(result[GEN_AI_TOOL_TYPE_KEY], "function")
        self.assertNotIn(GEN_AI_OPERATION_NAME_KEY, result)
        self.assertNotIn(GEN_AI_TOOL_ARGS_KEY, result)

    @patch("microsoft.opentelemetry._genai._langchain._utils._should_capture_content_on_spans", return_value=True)
    def test_extracts_function_call_content_when_enabled(self, _mock_capture):
        outputs = {
            "generations": [
                [
                    {
                        "message": {
                            "kwargs": {
                                "additional_kwargs": {
                                    "function_call": {
                                        "name": "get_weather",
                                        "arguments": '{"city": "NYC"}',
                                        "result": {"temperature": "72F"},
                                    }
                                }
                            }
                        }
                    }
                ]
            ]
        }
        result = dict(function_calls(outputs))
        self.assertEqual(result[GEN_AI_TOOL_ARGS_KEY], '{"city":"NYC"}')
        self.assertEqual(result[GEN_AI_TOOL_CALL_RESULT_KEY], '{"temperature":"72F"}')

    def test_returns_empty_on_none(self):
        self.assertEqual(list(function_calls(None)), [])


class TestTools(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._utils._should_capture_content_on_spans", return_value=False)
    def test_extracts_tool_info(self, _mock_capture):
        run = _make_run(
            run_type="tool",
            serialized={"name": "calculator", "description": "Does math"},
            inputs={"input": "2+2"},
            outputs={"output": "4"},
            extra={"tool_call_id": "tc-1"},
        )
        result = dict(tools(run))
        self.assertEqual(result[GEN_AI_TOOL_NAME_KEY], "calculator")
        self.assertEqual(result[GEN_AI_TOOL_DESCRIPTION_KEY], "Does math")
        self.assertEqual(result[GEN_AI_TOOL_TYPE_KEY], "function")
        self.assertNotIn(GEN_AI_TOOL_ARGS_KEY, result)
        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT_KEY, result)
        self.assertEqual(result[GEN_AI_TOOL_CALL_ID_KEY], "tc-1")

    @patch("microsoft.opentelemetry._genai._langchain._utils._should_capture_content_on_spans", return_value=True)
    def test_extracts_tool_payloads_when_content_capture_enabled(self, _mock_capture):
        run = _make_run(
            run_type="tool",
            serialized={"name": "calculator", "description": "Does math"},
            inputs={"input": "2+2"},
            outputs={"output": "4"},
            extra={"tool_call_id": "tc-1"},
        )
        result = dict(tools(run))
        self.assertEqual(result[GEN_AI_TOOL_TYPE_KEY], "function")
        self.assertEqual(result[GEN_AI_TOOL_ARGS_KEY], "2+2")
        self.assertEqual(result[GEN_AI_TOOL_CALL_RESULT_KEY], "4")

    def test_skips_non_tool(self):
        run = _make_run(run_type="llm", serialized={"name": "calc"})
        self.assertEqual(list(tools(run)), [])


class TestChainNodeMessages(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._utils._should_capture_content_on_spans", return_value=False)
    def test_skips_messages_when_content_capture_disabled(self, _mock_capture):
        data = {"messages": [{"content": "Hello", "role": "human"}]}
        self.assertEqual(list(chain_node_messages(data, GEN_AI_INPUT_MESSAGES_KEY)), [])

    @patch("microsoft.opentelemetry._genai._langchain._utils._should_capture_content_on_spans", return_value=True)
    def test_extracts_messages_from_dict(self, _mock_capture):
        data = {"messages": [{"content": "Hello", "role": "human"}]}
        result = list(chain_node_messages(data, GEN_AI_INPUT_MESSAGES_KEY))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], GEN_AI_INPUT_MESSAGES_KEY)
        self.assertIn("human: Hello", result[0][1])

    def test_returns_empty_on_none(self):
        self.assertEqual(list(chain_node_messages(None, GEN_AI_INPUT_MESSAGES_KEY)), [])

    def test_returns_empty_on_no_messages(self):
        self.assertEqual(list(chain_node_messages({"other": 1}, GEN_AI_INPUT_MESSAGES_KEY)), [])


class TestAddOperationType(TestCase):
    def test_llm_type(self):
        run = _make_run(run_type="llm")
        result = dict(add_operation_type(run))
        self.assertEqual(result[GEN_AI_OPERATION_NAME_KEY], CHAT_OPERATION_NAME)

    def test_chat_model_type(self):
        run = _make_run(run_type="chat_model")
        result = dict(add_operation_type(run))
        self.assertEqual(result[GEN_AI_OPERATION_NAME_KEY], CHAT_OPERATION_NAME)

    def test_tool_type(self):
        run = _make_run(run_type="tool")
        result = dict(add_operation_type(run))
        self.assertEqual(result[GEN_AI_OPERATION_NAME_KEY], EXECUTE_TOOL_OPERATION_NAME)

    def test_chain_type_returns_empty(self):
        run = _make_run(run_type="chain")
        self.assertEqual(list(add_operation_type(run)), [])


# ---- Agent I/O extractors ---------------------------------------------------


class TestInvokeAgentInputMessage(TestCase):
    def test_extracts_human_message(self):
        inputs = {"messages": [{"role": "human", "content": "What is 2+2?"}]}
        result = list(invoke_agent_input_message(inputs))
        self.assertEqual(result, [(GEN_AI_INPUT_MESSAGES_KEY, "What is 2+2?")])

    def test_extracts_from_nested_list(self):
        inputs = {"messages": [[{"role": "human", "content": "Hello"}]]}
        result = list(invoke_agent_input_message(inputs))
        self.assertEqual(result, [(GEN_AI_INPUT_MESSAGES_KEY, "Hello")])

    def test_returns_empty_on_none(self):
        self.assertEqual(list(invoke_agent_input_message(None)), [])


class TestInvokeAgentOutputMessage(TestCase):
    def test_extracts_ai_message(self):
        outputs = {"messages": [{"role": "ai", "content": "The answer is 4"}]}
        result = list(invoke_agent_output_message(outputs))
        self.assertEqual(result, [(GEN_AI_OUTPUT_MESSAGES_KEY, "The answer is 4")])

    def test_returns_empty_on_none(self):
        self.assertEqual(list(invoke_agent_output_message(None)), [])

    def test_extracts_last_ai_message(self):
        outputs = {
            "messages": [
                {"role": "ai", "content": "First"},
                {"role": "human", "content": "Again"},
                {"role": "ai", "content": "Second"},
            ]
        }
        result = list(invoke_agent_output_message(outputs))
        self.assertEqual(result, [(GEN_AI_OUTPUT_MESSAGES_KEY, "Second")])


# ---- Agent structured message extractors ------------------------------------


class TestExtractAgentInputMessages(TestCase):
    def test_extracts_structured_human_message(self):
        inputs = {"messages": [{"role": "human", "content": "What is 2+2?"}]}
        result = _extract_agent_input_messages(inputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role, "user")
        self.assertEqual(len(result[0].parts), 1)
        self.assertEqual(result[0].parts[0].content, "What is 2+2?")

    def test_extracts_multiple_messages(self):
        inputs = {
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "human", "content": "Hello"},
            ]
        }
        result = _extract_agent_input_messages(inputs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].role, "system")
        self.assertEqual(result[1].role, "user")

    def test_extracts_from_nested_list(self):
        inputs = {"messages": [[{"role": "human", "content": "Hello"}]]}
        result = _extract_agent_input_messages(inputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].parts[0].content, "Hello")

    def test_returns_empty_on_none(self):
        self.assertEqual(_extract_agent_input_messages(None), [])

    def test_returns_empty_on_no_messages(self):
        self.assertEqual(_extract_agent_input_messages({"other": "data"}), [])


class TestExtractAgentOutputMessages(TestCase):
    def test_extracts_structured_ai_message(self):
        outputs = {"messages": [{"role": "ai", "content": "The answer is 4"}]}
        result = _extract_agent_output_messages(outputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role, "assistant")
        self.assertEqual(result[0].parts[0].content, "The answer is 4")
        self.assertEqual(result[0].finish_reason, "stop")

    def test_returns_empty_on_none(self):
        self.assertEqual(_extract_agent_output_messages(None), [])

    def test_extracts_last_ai_message(self):
        outputs = {
            "messages": [
                {"role": "ai", "content": "First"},
                {"role": "human", "content": "Again"},
                {"role": "ai", "content": "Second"},
            ]
        }
        result = _extract_agent_output_messages(outputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].parts[0].content, "Second")

    def test_skips_empty_content(self):
        outputs = {"messages": [{"role": "ai", "content": ""}]}
        result = _extract_agent_output_messages(outputs)
        self.assertEqual(result, [])

    def test_extracts_from_nested_list(self):
        outputs = {"messages": [[{"role": "ai", "content": "Nested answer"}]]}
        result = _extract_agent_output_messages(outputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].parts[0].content, "Nested answer")


# ---- Agent metadata extractors -----------------------------------------------


class TestExtractAgentMetadata(TestCase):
    def test_extracts_from_metadata(self):
        run = _make_run(
            extra={"metadata": {"agent_name": "TravelBot", "agent_id": "a-1", "agent_description": "Helps travel"}},
        )
        result = dict(extract_agent_metadata(run))
        self.assertEqual(result[GEN_AI_AGENT_NAME_KEY], "TravelBot")
        self.assertEqual(result[GEN_AI_AGENT_ID_KEY], "a-1")
        self.assertEqual(result[GEN_AI_AGENT_DESCRIPTION_KEY], "Helps travel")

    def test_extracts_from_serialized(self):
        run = _make_run(
            extra=None,
            serialized={"name": "MyAgent"},
        )
        result = dict(extract_agent_metadata(run))
        self.assertEqual(result[GEN_AI_AGENT_NAME_KEY], "MyAgent")

    def test_skips_langgraph_name(self):
        run = _make_run(extra=None, serialized={"name": "LangGraph"})
        result = dict(extract_agent_metadata(run))
        self.assertNotIn(GEN_AI_AGENT_NAME_KEY, result)


class TestExtractSessionInfo(TestCase):
    def test_extracts_session_id(self):
        run = _make_run(extra={"metadata": {"session_id": "s-1"}})
        result = dict(extract_session_info(run))
        self.assertEqual(result[GEN_AI_CONVERSATION_ID_KEY], "s-1")

    def test_extracts_conversation_id(self):
        run = _make_run(extra={"metadata": {"conversation_id": "c-1"}})
        result = dict(extract_session_info(run))
        self.assertIn(GEN_AI_CONVERSATION_ID_KEY, result)
        self.assertEqual(result[GEN_AI_CONVERSATION_ID_KEY], "c-1")

    def test_extracts_thread_id(self):
        run = _make_run(extra={"metadata": {"thread_id": "t-1"}})
        result = dict(extract_session_info(run))
        self.assertEqual(result[GEN_AI_CONVERSATION_ID_KEY], "t-1")

    def test_returns_empty_on_no_metadata(self):
        run = _make_run(extra=None)
        self.assertEqual(list(extract_session_info(run)), [])


# ---- build_llm_invocation ---------------------------------------------------


class TestBuildLlmInvocation(TestCase):
    def test_builds_invocation_with_model(self):
        run = _make_run(
            run_type="llm",
            outputs={"llm_output": {"model_name": "gpt-4"}},
            extra={"metadata": {"ls_provider": "OpenAI"}},
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.request_model, "gpt-4")
        self.assertEqual(inv.provider, "openai")

    def test_builds_invocation_with_tokens(self):
        run = _make_run(
            run_type="llm",
            outputs={
                "llm_output": {"token_usage": {"prompt_tokens": 10, "completion_tokens": 20}},
                "generations": [],
            },
            extra=None,
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.input_tokens, 10)
        self.assertEqual(inv.output_tokens, 20)

    def test_builds_invocation_minimal(self):
        run = _make_run(run_type="llm", outputs=None, extra=None, inputs=None)
        inv = build_llm_invocation(run)
        self.assertIsNone(inv.request_model)

    def test_builds_invocation_with_request_parameters(self):
        run = _make_run(
            run_type="llm",
            outputs={"llm_output": {"model_name": "gpt-4o", "id": "resp-1"}},
            extra={
                "invocation_params": {
                    "temperature": "0.5",
                    "top_p": "0.9",
                    "max_tokens": "256",
                    "frequency_penalty": "0.1",
                    "presence_penalty": "0.2",
                    "seed": "7",
                    "stop": ["END"],
                    "base_url": "https://example.test/",
                }
            },
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.temperature, 0.5)
        self.assertEqual(inv.top_p, 0.9)
        self.assertEqual(inv.max_tokens, 256)
        self.assertEqual(inv.frequency_penalty, 0.1)
        self.assertEqual(inv.presence_penalty, 0.2)
        self.assertEqual(inv.seed, 7)
        self.assertEqual(inv.stop_sequences, ["END"])
        self.assertEqual(inv.server_address, "example.test")
        self.assertEqual(inv.response_model_name, "gpt-4o")
        self.assertEqual(inv.response_id, "resp-1")

    def test_builds_invocation_with_model_kwargs_and_alt_endpoint_keys(self):
        run = _make_run(
            run_type="llm",
            outputs={"llm_output": {"model_name": "gpt-4o", "id": "resp-2"}},
            extra={
                "invocation_params": {
                    "openai_api_base": "https://api.contoso.test/v1",
                    "model_kwargs": {
                        "temperature": "0.3",
                        "top_p": "0.8",
                        "max_output_tokens": "128",
                        "frequency_penalty": "0.4",
                        "presence_penalty": "0.6",
                        "stop_sequences": ["STOP"],
                    },
                }
            },
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.temperature, 0.3)
        self.assertEqual(inv.top_p, 0.8)
        self.assertEqual(inv.max_tokens, 128)
        self.assertEqual(inv.frequency_penalty, 0.4)
        self.assertEqual(inv.presence_penalty, 0.6)
        self.assertEqual(inv.stop_sequences, ["STOP"])
        self.assertEqual(inv.server_address, "api.contoso.test")

    def test_builds_invocation_server_address_from_metadata(self):
        run = _make_run(
            run_type="llm",
            outputs={"llm_output": {}},
            extra={"metadata": {"ls_server_address": "https://meta.contoso.test/"}},
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.server_address, "meta.contoso.test")

    def test_response_model_from_generation_metadata(self):
        # Simulates LangChain AzureChatOpenAI streaming / httpx pipeline:
        # ``llm_output`` is empty but ``response.model`` lives in each
        # generation's ``response_metadata`` (and ``id`` likewise).
        from langchain_core.messages import AIMessage

        ai_msg = AIMessage(content="hi")
        ai_msg.response_metadata = {"model_name": "gpt-4o-2024-08-06", "id": "chatcmpl-abc"}
        run = _make_run(
            run_type="llm",
            outputs={
                "llm_output": None,
                "generations": [[{"message": ai_msg, "generation_info": {"finish_reason": "stop"}}]],
            },
            extra={"metadata": {"ls_model_name": "gpt-4o"}},
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.response_model_name, "gpt-4o-2024-08-06")
        self.assertEqual(inv.response_id, "chatcmpl-abc")
        # Request model still comes from the request-side metadata.
        self.assertEqual(inv.request_model, "gpt-4o")

    def test_response_model_from_generation_info(self):
        run = _make_run(
            run_type="llm",
            outputs={
                "llm_output": {},
                "generations": [
                    [{"message": {"content": "hi"}, "generation_info": {"model_name": "gpt-4o-mini-2024-07-18"}}]
                ],
            },
            extra=None,
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.response_model_name, "gpt-4o-mini-2024-07-18")

    def test_response_model_from_message_kwargs_response_metadata(self):
        # Some serialized LangChain payloads nest response_metadata under
        # ``message.kwargs.response_metadata``. Ensure the fallback walks into it.
        run = _make_run(
            run_type="llm",
            outputs={
                "llm_output": None,
                "generations": [
                    [
                        {
                            "message": {
                                "kwargs": {
                                    "content": "hi",
                                    "response_metadata": {
                                        "model_name": "gpt-4o-2024-11-20",
                                        "id": "chatcmpl-kwargs",
                                    },
                                }
                            }
                        }
                    ]
                ],
            },
            extra=None,
            inputs=None,
        )
        inv = build_llm_invocation(run)
        self.assertEqual(inv.response_model_name, "gpt-4o-2024-11-20")
        self.assertEqual(inv.response_id, "chatcmpl-kwargs")


# ---- Spec-compliant input.messages (issue #172) ------------------------------


class TestExtractStructuredInputMessagesSpecCompliance(TestCase):
    """Verify input/output message extraction satisfies the OTel GenAI semconv
    for invoke_agent spans (issue #172)."""

    def test_normalizes_human_role_to_user(self):
        from langchain_core.messages import HumanMessage

        from microsoft.opentelemetry._genai._langchain._utils import (
            _extract_structured_input_messages,
        )

        result = _extract_structured_input_messages({"messages": [[HumanMessage(content="hi")]]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role, "user")
        self.assertEqual(result[0].parts[0].content, "hi")

    def test_assistant_role_for_ai_message(self):
        from langchain_core.messages import AIMessage

        from microsoft.opentelemetry._genai._langchain._utils import (
            _extract_structured_input_messages,
        )

        result = _extract_structured_input_messages({"messages": [[AIMessage(content="ok")]]})
        self.assertEqual(result[0].role, "assistant")

    def test_emits_tool_call_response_for_tool_message(self):
        from langchain_core.messages import ToolMessage

        from microsoft.opentelemetry._genai._langchain._utils import (
            _extract_structured_input_messages,
        )

        tool_msg = ToolMessage(content="rainy, 57F", tool_call_id="call_123")
        result = _extract_structured_input_messages({"messages": [[tool_msg]]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role, "tool")
        self.assertEqual(len(result[0].parts), 1)
        part = result[0].parts[0]
        self.assertEqual(part.type, "tool_call_response")
        self.assertEqual(part.id, "call_123")
        self.assertEqual(part.response, "rainy, 57F")

    def test_full_react_agent_history(self):
        """user -> assistant(tool_call) -> tool(tool_call_response) -> assistant"""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from microsoft.opentelemetry._genai._langchain._utils import (
            _extract_structured_input_messages,
        )

        history = [
            HumanMessage(content="Weather in Paris?"),
            AIMessage(
                content="",
                tool_calls=[{"name": "get_weather", "args": {"location": "Paris"}, "id": "call_1"}],
            ),
            ToolMessage(content="rainy, 57F", tool_call_id="call_1"),
        ]
        result = _extract_structured_input_messages({"messages": [history]})
        self.assertEqual([m.role for m in result], ["user", "assistant", "tool"])
        # assistant should carry a tool_call part
        assistant_parts = result[1].parts
        self.assertEqual(assistant_parts[0].type, "tool_call")
        self.assertEqual(assistant_parts[0].name, "get_weather")
        self.assertEqual(assistant_parts[0].id, "call_1")
        # tool message should carry tool_call_response, not Text
        tool_parts = result[2].parts
        self.assertEqual(tool_parts[0].type, "tool_call_response")
        self.assertEqual(tool_parts[0].id, "call_1")
        self.assertEqual(tool_parts[0].response, "rainy, 57F")
