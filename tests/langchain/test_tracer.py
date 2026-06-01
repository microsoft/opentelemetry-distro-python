# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytest.importorskip("langchain_core")

from microsoft.opentelemetry._genai._langchain._tracer import (  # noqa: E402  # pylint: disable=wrong-import-position
    LangChainTracer,
    _update_span,
    get_attributes_from_context,
)
from microsoft.opentelemetry._genai._langchain._utils import (  # noqa: E402  # pylint: disable=wrong-import-position
    EXECUTE_TOOL_OPERATION_NAME,
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
    GEN_AI_PROVIDER_NAME_KEY,
    GEN_AI_REQUEST_CHOICE_COUNT_KEY,
    GEN_AI_TOOL_DEFINITIONS_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)

pytest.importorskip("langchain_core")

_NOW = datetime.datetime(2024, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_NOW_END = datetime.datetime(2024, 6, 1, 12, 0, 1, tzinfo=datetime.timezone.utc)


# pylint: disable=unused-variable, broad-exception-caught
def _make_run(**kwargs):
    """Create a minimal mock Run."""
    run = MagicMock()
    run.id = kwargs.get("id", uuid4())
    run.name = kwargs.get("name", "test_run")
    run.run_type = kwargs.get("run_type", "chain")
    run.inputs = kwargs.get("inputs", None)
    run.outputs = kwargs.get("outputs", None)
    run.extra = kwargs.get("extra", None)
    run.serialized = kwargs.get("serialized", None)
    run.error = kwargs.get("error", None)
    run.parent_run_id = kwargs.get("parent_run_id", None)
    run.start_time = kwargs.get("start_time", _NOW)
    run.end_time = kwargs.get("end_time", _NOW_END)
    return run


def _make_tracer(**kwargs):
    """Create a LangChainTracer with mocked OTel tracer."""
    otel_tracer = MagicMock()
    mock_span = MagicMock()
    otel_tracer.start_span.return_value = mock_span
    tracer = LangChainTracer(
        otel_tracer,
        kwargs.get("separate_trace", False),
        agent_config=kwargs.get("agent_config", {}),
        event_logger=kwargs.get("event_logger", None),
    )
    return tracer, otel_tracer, mock_span


# ---- Static helpers ----------------------------------------------------------


class TestEvictTrackedRuns(TestCase):
    def test_evicts_oldest_entries_from_all_dicts(self):
        tracer, _, _ = _make_tracer()
        tracer._MAX_TRACKED_RUNS = 5
        uuids = [UUID(int=i) for i in range(10)]
        for uid in uuids:
            tracer._spans_by_run[uid] = f"span-{uid}"
            tracer._agent_run_ids.add(uid)
            tracer._agent_content[uid] = {"model": None}
            tracer._agent_wrapper_spans[uid] = f"wrapper-{uid}"
            tracer._context_tokens[uid] = []
            tracer.run_map[str(uid)] = f"run-{uid}"
        tracer._evict_tracked_runs()
        # Only 5 newest entries remain
        self.assertEqual(len(tracer._spans_by_run), 5)
        self.assertNotIn(uuids[0], tracer._spans_by_run)
        self.assertIn(uuids[9], tracer._spans_by_run)
        # Related dicts also cleaned up
        for uid in uuids[:5]:
            self.assertNotIn(uid, tracer._agent_run_ids)
            self.assertNotIn(uid, tracer._agent_content)
            self.assertNotIn(uid, tracer._agent_wrapper_spans)
            self.assertNotIn(uid, tracer._context_tokens)
            self.assertNotIn(str(uid), tracer.run_map)
        for uid in uuids[5:]:
            self.assertIn(uid, tracer._agent_run_ids)
            self.assertIn(uid, tracer._agent_content)
            self.assertIn(uid, tracer._agent_wrapper_spans)


# ---- Agent detection ---------------------------------------------------------


class TestIsAgentLikeChain(TestCase):
    def test_langgraph_name(self):
        run = _make_run(run_type="chain", name="LangGraph")
        self.assertTrue(LangChainTracer._is_agent_like_chain(run))

    def test_compiled_graph(self):
        run = _make_run(
            run_type="chain",
            name="MyGraph",
            serialized={"graph": {"type": "CompiledGraph"}},
        )
        self.assertTrue(LangChainTracer._is_agent_like_chain(run))

    def test_state_graph(self):
        run = _make_run(
            run_type="chain",
            name="MyGraph",
            serialized={"graph": {"type": "StateGraph"}},
        )
        self.assertTrue(LangChainTracer._is_agent_like_chain(run))

    def test_agent_in_name(self):
        run = _make_run(run_type="chain", name="MyAgent")
        self.assertTrue(LangChainTracer._is_agent_like_chain(run))

    def test_lc_agent_name_in_metadata(self):
        run = _make_run(
            run_type="chain",
            name="Travel_Assistant",
            extra={"metadata": {"lc_agent_name": "Travel_Assistant"}},
        )
        self.assertTrue(LangChainTracer._is_agent_like_chain(run))

    def test_non_chain_returns_false(self):
        run = _make_run(run_type="llm", name="LangGraph")
        self.assertFalse(LangChainTracer._is_agent_like_chain(run))

    def test_plain_chain_returns_false(self):
        run = _make_run(run_type="chain", name="RunnableSequence")
        self.assertFalse(LangChainTracer._is_agent_like_chain(run))


class TestIsAgentRun(TestCase):
    def test_top_level_agent(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(run_type="chain", name="LangGraph", parent_run_id=None)
        self.assertTrue(tracer._is_agent_run(run))

    def test_nested_agent_returns_false(self):
        tracer, _, _ = _make_tracer()
        parent_id = uuid4()
        tracer._agent_run_ids.add(parent_id)
        run = _make_run(run_type="chain", name="LangGraph", parent_run_id=parent_id)
        self.assertFalse(tracer._is_agent_run(run))

    def test_non_agent_returns_false(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        self.assertFalse(tracer._is_agent_run(run))


# ---- Agent name resolution ---------------------------------------------------


class TestResolveAgentName(TestCase):
    def test_config_override(self):
        tracer, _, _ = _make_tracer(agent_config={"agent_name": "ConfigBot"})
        run = _make_run(run_type="chain", name="LangGraph")
        self.assertEqual(tracer._resolve_agent_name(run), "ConfigBot")

    def test_metadata_agent_name(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"agent_name": "MetaBot"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "MetaBot")

    def test_metadata_lc_agent_name(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="Travel_Assistant",
            extra={"metadata": {"lc_agent_name": "Travel_Assistant"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "Travel_Assistant")

    def test_serialized_name(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            serialized={"name": "CustomGraph"},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "CustomGraph")

    def test_run_name_fallback(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(run_type="chain", name="MyAgent")
        self.assertEqual(tracer._resolve_agent_name(run), "MyAgent")

    def test_langgraph_name_returns_none(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(run_type="chain", name="LangGraph")
        self.assertIsNone(tracer._resolve_agent_name(run))


# ---- Framework name resolution -----------------------------------------------


class TestResolveFrameworkName(TestCase):
    def test_compiled_graph_returns_langgraph(self):
        run = _make_run(serialized={"graph": {"type": "CompiledGraph"}})
        self.assertEqual(LangChainTracer._resolve_framework_name(run), "LangGraph")

    def test_state_graph_returns_langgraph(self):
        run = _make_run(serialized={"graph": {"type": "StateGraph"}})
        self.assertEqual(LangChainTracer._resolve_framework_name(run), "LangGraph")

    def test_serialized_name_different_from_run(self):
        run = _make_run(name="Travel_Assistant", serialized={"name": "CustomFramework"})
        self.assertEqual(LangChainTracer._resolve_framework_name(run), "CustomFramework")

    def test_defaults_to_langgraph(self):
        run = _make_run(name="Travel_Assistant", serialized=None)
        self.assertEqual(LangChainTracer._resolve_framework_name(run), "LangGraph")

    def test_same_serialized_and_run_name_defaults(self):
        run = _make_run(name="Travel_Assistant", serialized={"name": "Travel_Assistant"})
        self.assertEqual(LangChainTracer._resolve_framework_name(run), "LangGraph")


# ---- _start_trace / _end_trace -----------------------------------------------


class TestStartTrace(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_creates_span_for_chain(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        tracer._start_trace(run)
        otel_tracer.start_span.assert_called_once()
        args = otel_tracer.start_span.call_args
        self.assertEqual(args.kwargs["name"], "RunnableSequence")

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_creates_span_for_tool(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(run_type="tool", name="get_weather")
        tracer._start_trace(run)
        otel_tracer.start_span.assert_called_once()
        args = otel_tracer.start_span.call_args
        self.assertIn(EXECUTE_TOOL_OPERATION_NAME, args.kwargs["name"])
        self.assertIn("get_weather", args.kwargs["name"])

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_creates_wrapper_for_agent(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="Travel_Assistant",
            extra={"metadata": {"lc_agent_name": "Travel_Assistant"}},
        )
        tracer._start_trace(run)
        # Two spans: wrapper + inner
        self.assertEqual(otel_tracer.start_span.call_count, 2)
        calls = otel_tracer.start_span.call_args_list
        wrapper_name = calls[0].kwargs["name"]
        inner_name = calls[1].kwargs["name"]
        self.assertIn("Travel_Assistant", wrapper_name)
        self.assertIn(INVOKE_AGENT_OPERATION_NAME, wrapper_name)
        self.assertIn("LangGraph", inner_name)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_suppressed_instrumentation_skips(self, mock_ctx):
        mock_ctx.get_value.return_value = True
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(run_type="chain", name="test")
        tracer._start_trace(run)
        otel_tracer.start_span.assert_not_called()


class TestEndTrace(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_ends_span(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(run_type="chain", name="test")
        tracer._start_trace(run)
        tracer._end_trace(run)
        mock_span.end.assert_called()

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_ends_both_spans_for_agent(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper_span = MagicMock()
        inner_span = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper_span, inner_span]
        run = _make_run(
            run_type="chain",
            name="Travel_Assistant",
            extra={"metadata": {"lc_agent_name": "Travel_Assistant"}},
        )
        tracer._start_trace(run)
        tracer._end_trace(run)
        inner_span.end.assert_called_once()
        wrapper_span.end.assert_called_once()

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_cleans_up_agent_tracking(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper_span = MagicMock()
        inner_span = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper_span, inner_span]
        run = _make_run(
            run_type="chain",
            name="LangGraph",
        )
        tracer._start_trace(run)
        self.assertIn(run.id, tracer._agent_run_ids)
        tracer._end_trace(run)
        self.assertNotIn(run.id, tracer._agent_run_ids)
        self.assertNotIn(run.id, tracer._agent_content)


# ---- Error handlers ----------------------------------------------------------


class TestErrorHandlers(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_on_llm_error_records_exception(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(run_type="llm", name="gpt-4")
        tracer._start_trace(run)
        error = ValueError("test error")
        with patch.object(tracer, "_persist_run"):
            try:
                tracer.on_llm_error(error, run_id=run.id)
            except Exception:
                pass
        mock_span.record_exception.assert_called_with(error)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_on_chain_error_records_exception(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(run_type="chain", name="test")
        tracer._start_trace(run)
        error = RuntimeError("chain failed")
        with patch.object(tracer, "_persist_run"):
            try:
                tracer.on_chain_error(error, run_id=run.id)
            except Exception:
                pass
        mock_span.record_exception.assert_called_with(error)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_on_tool_error_records_exception(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(run_type="tool", name="calc")
        tracer._start_trace(run)
        error = RuntimeError("tool failed")
        with patch.object(tracer, "_persist_run"):
            try:
                tracer.on_tool_error(error, run_id=run.id)
            except Exception:
                pass
        mock_span.record_exception.assert_called_with(error)


# ---- _update_span ------------------------------------------------------------


class TestUpdateSpan(TestCase):
    def test_sets_ok_status_on_no_error(self):
        span = MagicMock()
        run = _make_run(run_type="chain", name="test", error=None)
        _update_span(span, run)
        span.set_status.assert_called()

    def test_llm_run_returns_invocation(self):
        span = MagicMock()
        run = _make_run(
            run_type="llm",
            name="gpt-4",
            outputs={"llm_output": {"model_name": "gpt-4"}, "generations": []},
            extra=None,
            inputs=None,
        )
        result = _update_span(span, run)
        self.assertIsNotNone(result)

    def test_chain_run_returns_none(self):
        span = MagicMock()
        run = _make_run(run_type="chain", name="test")
        result = _update_span(span, run)
        self.assertIsNone(result)

    def test_tool_run_sets_tool_attributes(self):
        span = MagicMock()
        run = _make_run(
            run_type="tool",
            name="calculator",
            serialized={"name": "calculator", "description": "Math tool"},
            inputs={"input": "2+2"},
            outputs={"output": "4"},
        )
        _update_span(span, run)
        span.set_attributes.assert_called()

    def test_chat_span_sets_provider_and_choice_count(self):
        span = MagicMock()
        run = _make_run(
            run_type="chat_model",
            name="gpt-4o",
            extra={"invocation_params": {"use_responses_api": True, "model": "gpt-4o"}},
            outputs={
                "generations": [
                    {"message": {"content": "a"}},
                    {"message": {"content": "b"}},
                ]
            },
            inputs=None,
        )

        _update_span(span, run)

        merged_attrs = {}
        for call in span.set_attributes.call_args_list:
            if call.args and isinstance(call.args[0], dict):
                merged_attrs.update(call.args[0])

        self.assertEqual(merged_attrs.get(GEN_AI_PROVIDER_NAME_KEY), "openai")
        self.assertEqual(merged_attrs.get(GEN_AI_REQUEST_CHOICE_COUNT_KEY), 2)


# ---- Aggregation -------------------------------------------------------------


class TestAggregateIntoParent(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_aggregates_llm_model(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        llm_run = _make_run(
            run_type="llm",
            name="gpt-4",
            parent_run_id=agent_run.id,
            outputs={"llm_output": {"model_name": "gpt-4"}, "generations": []},
            extra=None,
            inputs={"messages": [[{"content": "Hello"}]]},
        )
        tracer.run_map[str(llm_run.id)] = llm_run
        tracer._aggregate_into_parent(llm_run)

        content = tracer._agent_content[agent_run.id]
        self.assertEqual(content["model"], "gpt-4")

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_tool_run_does_not_pollute_output_messages(self, mock_ctx):
        """Per GenAI semconv, the wrapper invoke_agent span's
        gen_ai.output.messages must reflect only the final assistant
        choice(s). Tool results belong on gen_ai.input.messages via the
        cumulative chat history captured from the last LLM child."""
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        tool_run = _make_run(
            run_type="tool",
            name="calculator",
            parent_run_id=agent_run.id,
            outputs={"output": "42"},
        )
        tracer.run_map[str(tool_run.id)] = tool_run
        tracer._aggregate_into_parent(tool_run)

        content = tracer._agent_content[agent_run.id]
        # Tool output is no longer appended to the agent's output_messages.
        self.assertEqual(content["output_messages"], [])

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_aggregates_tokens_from_generation_info_usage(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        llm_run = _make_run(
            run_type="llm",
            name="gpt-4o",
            parent_run_id=agent_run.id,
            outputs={
                "generations": [[{"generation_info": {"usage": {"prompt_tokens": 11, "completion_tokens": 4}}}]],
            },
            extra=None,
            inputs=None,
        )
        tracer.run_map[str(llm_run.id)] = llm_run
        tracer._aggregate_into_parent(llm_run)

        content = tracer._agent_content[agent_run.id]
        self.assertEqual(content["input_tokens"], 11)
        self.assertEqual(content["output_tokens"], 4)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_aggregates_tokens_from_message_usage_metadata_object(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        llm_run = _make_run(
            run_type="chat_model",
            name="gpt-4o-mini",
            parent_run_id=agent_run.id,
            outputs={
                "generations": [
                    [
                        {
                            "message": {
                                "usage_metadata": SimpleNamespace(
                                    input_tokens=9,
                                    output_tokens=3,
                                )
                            }
                        }
                    ]
                ]
            },
            extra=None,
            inputs=None,
        )
        tracer.run_map[str(llm_run.id)] = llm_run
        tracer._aggregate_into_parent(llm_run)

        content = tracer._agent_content[agent_run.id]
        self.assertEqual(content["input_tokens"], 9)
        self.assertEqual(content["output_tokens"], 3)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_aggregates_provider_and_choice_count(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        llm_run = _make_run(
            run_type="chat_model",
            name="gpt-4o",
            parent_run_id=agent_run.id,
            extra={"invocation_params": {"use_responses_api": True, "model": "gpt-4o"}},
            outputs={
                "generations": [
                    {"message": {"content": "a"}},
                    {"message": {"content": "b"}},
                ]
            },
            inputs=None,
        )
        tracer.run_map[str(llm_run.id)] = llm_run
        tracer._aggregate_into_parent(llm_run)

        content = tracer._agent_content[agent_run.id]
        self.assertEqual(content["provider"], "openai")
        self.assertEqual(content["request_choice_count"], 2)


class TestFindAgentAncestor(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_finds_direct_parent(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        child_run = _make_run(run_type="llm", name="gpt-4", parent_run_id=agent_run.id)
        tracer.run_map[str(child_run.id)] = child_run
        result = tracer._find_agent_ancestor(child_run)
        self.assertEqual(result, agent_run.id)

    def test_returns_none_without_parent(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(parent_run_id=None)
        self.assertIsNone(tracer._find_agent_ancestor(run))


# ---- get_attributes_from_context ---------------------------------------------


class TestGetAttributesFromContext(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.get_value")
    def test_yields_context_attributes(self, mock_get_value):
        mock_get_value.side_effect = lambda key: "test_val" if key == "session.id" else None
        result = dict(get_attributes_from_context())
        self.assertEqual(result.get("session.id"), "test_val")

    @patch("microsoft.opentelemetry._genai._langchain._tracer.get_value", return_value=None)
    def test_yields_nothing_when_empty(self, mock_get_value):
        result = list(get_attributes_from_context())
        self.assertEqual(result, [])


# ---- Runtime-context attach/detach (HTTP child-span parenting) ---------------


class TestRunInlineFlag(TestCase):
    """LangChain's async callback manager honors ``run_inline = True`` to
    invoke sync handlers on the asyncio task instead of dispatching to a
    thread-pool worker. This is required for our ``context_api.attach`` call
    in ``_start_trace`` to mutate the contextvars of the awaiting LLM call so
    that openai/httpx child spans correctly parent under our LLM span."""

    def test_run_inline_is_true(self):
        self.assertTrue(LangChainTracer.run_inline)


class TestContextAttachDetach(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_attaches_inner_span_to_runtime_context(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        mock_ctx.attach.return_value = "token-1"
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        tracer._start_trace(run)
        mock_ctx.attach.assert_called_once()
        self.assertEqual(tracer._context_tokens[run.id], ["token-1"])

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_detaches_on_end(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        mock_ctx.attach.return_value = "token-1"
        # Fake _RUNTIME_CONTEXT exposed on the patched module
        runtime = MagicMock()
        mock_ctx._RUNTIME_CONTEXT = runtime
        tracer, otel_tracer, mock_span = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        tracer._start_trace(run)
        tracer._end_trace(run)
        runtime.detach.assert_called_once_with("token-1")
        self.assertNotIn(run.id, tracer._context_tokens)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_skips_attach_when_separate_trace(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer(separate_trace=True)
        run = _make_run(run_type="chain", name="RunnableSequence")
        tracer._start_trace(run)
        mock_ctx.attach.assert_not_called()
        self.assertNotIn(run.id, tracer._context_tokens)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_detach_swallows_cross_context_error(self, mock_ctx):
        """Token created in a different Context raises ValueError on detach.
        The handler must swallow it (asyncio task contextvars are discarded
        when the task ends) without propagating or logging at error level."""
        mock_ctx.get_value.return_value = None
        mock_ctx.attach.return_value = "token-1"
        runtime = MagicMock()
        runtime.detach.side_effect = ValueError("Token created in different Context")
        mock_ctx._RUNTIME_CONTEXT = runtime
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        tracer._start_trace(run)
        # Must not raise.
        tracer._end_trace(run)
        runtime.detach.assert_called_once_with("token-1")

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_detach_falls_back_to_context_api_when_runtime_missing(self, mock_ctx):
        """If ``_RUNTIME_CONTEXT`` private attribute is unavailable, fall back
        to the public ``context_api.detach`` wrapper."""
        mock_ctx.get_value.return_value = None
        mock_ctx.attach.return_value = "token-1"
        # Simulate missing private attribute.
        if hasattr(mock_ctx, "_RUNTIME_CONTEXT"):
            del mock_ctx._RUNTIME_CONTEXT
        # ``getattr`` in tracer with default ``None`` triggers fallback.
        type(mock_ctx)._RUNTIME_CONTEXT = property(lambda self: None)  # type: ignore[attr-defined]
        try:
            tracer, otel_tracer, _ = _make_tracer()
            run = _make_run(run_type="chain", name="RunnableSequence")
            tracer._start_trace(run)
            tracer._end_trace(run)
            mock_ctx.detach.assert_called_once_with("token-1")
        finally:
            del type(mock_ctx)._RUNTIME_CONTEXT  # type: ignore[attr-defined]

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_no_token_stored_when_suppressed(self, mock_ctx):
        # SUPPRESS_INSTRUMENTATION skips the entire _start_trace body.
        mock_ctx.get_value.return_value = True
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        tracer._start_trace(run)
        mock_ctx.attach.assert_not_called()
        self.assertEqual(tracer._context_tokens, {})

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_attach_uses_inner_span_for_agent(self, mock_ctx):
        """For a two-span agent, the attached span must be the INNER span
        (so child LLM/tool runs parent under the framework span, and HTTP
        spans parent under the LLM span when its own _start_trace runs)."""
        mock_ctx.get_value.return_value = None
        mock_ctx.attach.return_value = "token-1"
        tracer, otel_tracer, _ = _make_tracer()
        wrapper_span = MagicMock(name="wrapper")
        inner_span = MagicMock(name="inner")
        otel_tracer.start_span.side_effect = [wrapper_span, inner_span]
        run = _make_run(
            run_type="chain",
            name="Travel_Assistant",
            extra={"metadata": {"lc_agent_name": "Travel_Assistant"}},
        )
        # Patch set_span_in_context to record the span passed in.
        with patch("microsoft.opentelemetry._genai._langchain._tracer.trace_api.set_span_in_context") as mock_sic:
            tracer._start_trace(run)
            # set_span_in_context is called twice during agent _start_trace:
            # 1. To re-parent the inner span under the wrapper (parent_context).
            # 2. To attach the inner span to the runtime context.
            attach_call_args = mock_sic.call_args_list[-1]
            self.assertIs(attach_call_args[0][0], inner_span)
        mock_ctx.attach.assert_called_once()


# ---- invoke_agent aggregation fixes (issue #172) -----------------------------


class TestAggregateInputMessagesLastWins(TestCase):
    """The wrapper invoke_agent span needs the full ordered chat history.
    Build it incrementally from the agent's own inputs + each child's
    outputs so we don't depend on LangChain handing the LLM a structured
    ``messages`` list (it often serialises to a prompt string instead --
    see issue #172)."""

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_last_llm_input_overrides_first(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(
            run_type="chain",
            name="LangGraph",
            inputs={"messages": [{"role": "user", "content": "Weather in Paris?"}]},
        )
        tracer.run_map[str(agent_run.id)] = agent_run
        tracer._start_trace(agent_run)

        # First LLM call: model emits an assistant message with a tool_call.
        first_llm = _make_run(
            run_type="chat_model",
            name="gpt-4o-mini",
            parent_run_id=agent_run.id,
            inputs={"prompts": ["Human: Weather in Paris?"]},
            outputs={
                "generations": [
                    [
                        {
                            "text": "",
                            "message": {
                                "id": ["langchain", "schema", "messages", "AIMessage"],
                                "kwargs": {
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "name": "get_weather",
                                            "args": {"location": "Paris"},
                                            "id": "c1",
                                        }
                                    ],
                                    "type": "ai",
                                },
                            },
                        }
                    ]
                ]
            },
            extra=None,
        )
        tracer.run_map[str(first_llm.id)] = first_llm
        tracer._aggregate_into_parent(first_llm)

        # Tool run produces the tool_call_response.
        tool_run = _make_run(
            run_type="tool",
            name="get_weather",
            parent_run_id=agent_run.id,
            inputs={"tool_call_id": "c1", "location": "Paris"},
            outputs={"output": "rainy"},
            extra=None,
        )
        tracer.run_map[str(tool_run.id)] = tool_run
        tracer._aggregate_into_parent(tool_run)

        # Second LLM call: final assistant reply.
        second_llm = _make_run(
            run_type="chat_model",
            name="gpt-4o-mini",
            parent_run_id=agent_run.id,
            inputs={"prompts": ["...serialized buffer..."]},
            outputs={
                "generations": [
                    [
                        {
                            "text": "It's rainy in Paris.",
                            "message": {
                                "id": ["langchain", "schema", "messages", "AIMessage"],
                                "kwargs": {
                                    "content": "It's rainy in Paris.",
                                    "type": "ai",
                                },
                            },
                        }
                    ]
                ]
            },
            extra=None,
        )
        tracer.run_map[str(second_llm.id)] = second_llm
        tracer._aggregate_into_parent(second_llm)

        content = tracer._agent_content[agent_run.id]
        roles = [m.role for m in content["input_messages"]]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        # Final assistant is held as pending_assistant until finalize.
        self.assertIsNotNone(content["pending_assistant"])
        self.assertEqual(content["pending_assistant"][0].role, "assistant")


class TestAggregateToolDefinitions(TestCase):
    """Aggregate gen_ai.tool.definitions from LLM children onto the wrapper."""

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_captures_tool_definitions_from_invocation_params(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(run_type="chain", name="LangGraph")
        tracer._start_trace(agent_run)

        tool_defs = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
                },
            }
        ]
        llm_run = _make_run(
            run_type="chat_model",
            name="gpt-4o",
            parent_run_id=agent_run.id,
            extra={"invocation_params": {"model": "gpt-4o", "tools": tool_defs}},
            outputs={"generations": []},
            inputs=None,
        )
        tracer.run_map[str(llm_run.id)] = llm_run
        tracer._aggregate_into_parent(llm_run)

        content = tracer._agent_content[agent_run.id]
        self.assertIn("tool_definitions", content)
        self.assertIn("get_weather", content["tool_definitions"])


class TestFinalizeAgentSpanAttributes(TestCase):
    """End-to-end finalize: assert the wrapper invoke_agent span actually
    receives ``gen_ai.input.messages``, ``gen_ai.output.messages``, and
    ``gen_ai.tool.definitions`` attributes with the correct shape."""

    @patch("microsoft.opentelemetry._genai._langchain._tracer._should_capture_content_on_spans")
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_finalize_writes_input_output_and_tool_definitions(self, mock_ctx, mock_capture):
        import json

        mock_ctx.get_value.return_value = None
        mock_capture.return_value = True

        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(
            run_type="chain",
            name="LangGraph",
            inputs={"messages": [("human", "Weather in Paris?")]},
            outputs={"messages": []},
        )
        tracer.run_map[str(agent_run.id)] = agent_run
        tracer._start_trace(agent_run)

        # LLM child #1: assistant emits a tool_call.
        tool_defs = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                },
            }
        ]
        llm_one = _make_run(
            run_type="chat_model",
            name="gpt-4o-mini",
            parent_run_id=agent_run.id,
            inputs={"prompts": ["Human: Weather in Paris?"]},
            extra={"invocation_params": {"model": "gpt-4o-mini", "tools": tool_defs}},
            outputs={
                "generations": [
                    [
                        {
                            "text": "",
                            "message": {
                                "id": ["langchain", "schema", "messages", "AIMessage"],
                                "kwargs": {
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "name": "get_weather",
                                            "args": {"location": "Paris"},
                                            "id": "tc1",
                                        }
                                    ],
                                    "type": "ai",
                                },
                            },
                        }
                    ]
                ]
            },
        )
        tracer.run_map[str(llm_one.id)] = llm_one
        tracer._aggregate_into_parent(llm_one)

        # Tool child returns weather.
        tool_run = _make_run(
            run_type="tool",
            name="get_weather",
            parent_run_id=agent_run.id,
            inputs={"tool_call_id": "tc1", "location": "Paris"},
            outputs={"output": "rainy"},
        )
        tracer.run_map[str(tool_run.id)] = tool_run
        tracer._aggregate_into_parent(tool_run)

        # LLM child #2: final assistant text.
        llm_two = _make_run(
            run_type="chat_model",
            name="gpt-4o-mini",
            parent_run_id=agent_run.id,
            inputs={"prompts": ["..."]},
            outputs={
                "generations": [
                    [
                        {
                            "text": "It's rainy in Paris.",
                            "message": {
                                "id": ["langchain", "schema", "messages", "AIMessage"],
                                "kwargs": {
                                    "content": "It's rainy in Paris.",
                                    "type": "ai",
                                },
                            },
                        }
                    ]
                ]
            },
        )
        tracer.run_map[str(llm_two.id)] = llm_two
        tracer._aggregate_into_parent(llm_two)

        tracer._finalize_agent_span(wrapper, agent_run)

        # Collect every (key, value) pair set on the wrapper span.
        attrs: dict[str, object] = {}
        for call in wrapper.set_attribute.call_args_list:  # pylint: disable=no-member
            attrs[call.args[0]] = call.args[1]

        self.assertIn(GEN_AI_INPUT_MESSAGES_KEY, attrs)
        self.assertIn(GEN_AI_OUTPUT_MESSAGES_KEY, attrs)
        self.assertIn(GEN_AI_TOOL_DEFINITIONS_KEY, attrs)

        input_msgs = json.loads(attrs[GEN_AI_INPUT_MESSAGES_KEY])
        roles = [m["role"] for m in input_msgs]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        # User part is text.
        self.assertEqual(input_msgs[0]["parts"][0]["type"], "text")
        self.assertIn("Paris", input_msgs[0]["parts"][0]["content"])
        # Assistant part is a tool_call with matching id.
        self.assertEqual(input_msgs[1]["parts"][0]["type"], "tool_call")
        self.assertEqual(input_msgs[1]["parts"][0]["id"], "tc1")
        # Tool part is a tool_call_response with matching id and the
        # unwrapped tool output (not a stringified ToolMessage repr).
        self.assertEqual(input_msgs[2]["parts"][0]["type"], "tool_call_response")
        self.assertEqual(input_msgs[2]["parts"][0]["id"], "tc1")
        self.assertEqual(input_msgs[2]["parts"][0]["response"], "rainy")

        output_msgs = json.loads(attrs[GEN_AI_OUTPUT_MESSAGES_KEY])
        self.assertEqual(len(output_msgs), 1)
        self.assertEqual(output_msgs[0]["role"], "assistant")
        self.assertEqual(output_msgs[0]["parts"][0]["content"], "It's rainy in Paris.")

        # Tool definitions preserved on the wrapper span.
        tool_defs_attr = attrs[GEN_AI_TOOL_DEFINITIONS_KEY]
        self.assertIn("get_weather", str(tool_defs_attr))


class TestExtractAgentInputMessagesToolRole(TestCase):
    """Pre-populated ReAct histories that include a tool-role message must
    surface as ``tool_call_response`` parts -- not plain text."""

    def test_tool_role_message_becomes_tool_call_response(self):
        from microsoft.opentelemetry._genai._langchain._utils import (
            _extract_agent_input_messages,
        )

        inputs = {
            "messages": [
                {"role": "user", "content": "Weather in Paris?"},
                {
                    "id": ["langchain", "schema", "messages", "AIMessage"],
                    "kwargs": {
                        "content": "",
                        "tool_calls": [{"name": "get_weather", "args": {"location": "Paris"}, "id": "tc1"}],
                        "type": "ai",
                    },
                },
                {"role": "tool", "content": "rainy", "tool_call_id": "tc1"},
            ]
        }
        msgs = _extract_agent_input_messages(inputs)
        roles = [m.role for m in msgs]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        tool_part = msgs[2].parts[0]
        self.assertEqual(tool_part.type, "tool_call_response")
        self.assertEqual(tool_part.id, "tc1")
        self.assertEqual(tool_part.response, "rainy")
