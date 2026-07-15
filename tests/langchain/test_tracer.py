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
    GEN_AI_AGENT_NAME_KEY,
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
            self.assertNotIn(uid, tracer._context_tokens)
            self.assertNotIn(str(uid), tracer.run_map)
        for uid in uuids[5:]:
            self.assertIn(uid, tracer._agent_run_ids)
            self.assertIn(uid, tracer._agent_content)


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

    def test_nested_agent_is_still_agent_like(self):
        """A nested agent-like chain is still detected as an agent run; the
        nesting itself is recognised separately via ``_find_agent_ancestor``
        (used by ``_start_trace`` to suppress config-derived identity for
        sub-agents), not by ``_is_agent_run`` returning ``False``."""
        tracer, _, _ = _make_tracer()
        parent_id = uuid4()
        tracer._agent_run_ids.add(parent_id)
        run = _make_run(run_type="chain", name="LangGraph", parent_run_id=parent_id)
        self.assertTrue(tracer._is_agent_run(run))
        self.assertEqual(tracer._find_agent_ancestor(run), parent_id)

    def test_non_agent_returns_false(self):
        tracer, _, _ = _make_tracer()
        run = _make_run(run_type="chain", name="RunnableSequence")
        self.assertFalse(tracer._is_agent_run(run))

    def test_deeply_nested_agent_finds_agent_ancestor(self):
        """An agent-like chain nested under a non-agent chain whose ancestor is
        already an agent is still agent-like, and ``_find_agent_ancestor``
        walks past the intermediate chain to locate the real agent ancestor
        (so token aggregation stays attributed to the top-level agent span)."""
        tracer, _, _ = _make_tracer()
        agent_id = uuid4()
        chain_id = uuid4()
        tracer._agent_run_ids.add(agent_id)
        # Intermediate non-agent chain between top-level agent and sub-graph.
        chain_run = _make_run(run_type="chain", name="node_step", id=chain_id, parent_run_id=agent_id)
        tracer.run_map[str(chain_id)] = chain_run
        # Sub-graph whose direct parent is the intermediate chain, not the agent.
        sub_graph = _make_run(run_type="chain", name="SubAgentGraph", parent_run_id=chain_id)
        self.assertTrue(tracer._is_agent_run(sub_graph))
        self.assertEqual(tracer._find_agent_ancestor(sub_graph), agent_id)


# ---- LangGraph node suppression ----------------------------------------------


def _node_run(node_name, *, parent_run_id=None, **meta):
    """Build a chain run tagged with a LangGraph node and extra metadata."""
    metadata = {"langgraph_node": node_name, **meta}
    return _make_run(
        run_type="chain",
        name="LangGraph",
        parent_run_id=parent_run_id,
        extra={"metadata": metadata},
    )


class TestShouldIgnoreLangGraphNode(TestCase):
    """Guards the suppression rules for genuine LangGraph nodes.  These
    rules decide which framework-internal nodes (``__start__``, middleware,
    identity-less orchestration nodes) are dropped vs. emitted as their own
    ``invoke_agent`` span, including the ``otel_trace`` / ``otel_agent_span``
    overrides."""

    def setUp(self):
        self.tracer, _, _ = _make_tracer()

    # --- otel_trace override (highest precedence) -----------------------------

    def test_otel_trace_true_forces_keep(self):
        run = _node_run("__start__", parent_run_id=uuid4(), otel_trace=True)
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    def test_otel_trace_false_forces_ignore(self):
        # Even the root (no parent) is suppressed when otel_trace is False.
        run = _node_run("agent", parent_run_id=None, otel_trace=False, agent_name="A")
        self.assertTrue(self.tracer._should_ignore_langgraph_node(run))

    # --- __start__ entrypoint -------------------------------------------------

    def test_start_node_ignored(self):
        run = _node_run("__start__", parent_run_id=uuid4())
        self.assertTrue(self.tracer._should_ignore_langgraph_node(run))

    # --- otel_agent_span override ---------------------------------------------

    def test_otel_agent_span_true_forces_keep(self):
        run = _node_run("model", parent_run_id=uuid4(), otel_agent_span=True)
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    def test_otel_agent_span_false_forces_ignore(self):
        run = _node_run("flight", parent_run_id=uuid4(), otel_agent_span=False, agent_name="Flight")
        self.assertTrue(self.tracer._should_ignore_langgraph_node(run))

    def test_otel_trace_wins_over_otel_agent_span(self):
        run = _node_run("model", parent_run_id=uuid4(), otel_trace=True, otel_agent_span=False)
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    # --- middleware prefix ----------------------------------------------------

    def test_middleware_prefix_ignored(self):
        run = _node_run("Middleware.summarize", parent_run_id=uuid4())
        self.assertTrue(self.tracer._should_ignore_langgraph_node(run))

    def test_middleware_only_matches_as_prefix_not_substring(self):
        """A node name that merely contains ``Middleware.`` somewhere other
        than the start must NOT be suppressed by the middleware rule."""
        run = _node_run("CustomMiddleware.step", parent_run_id=uuid4(), agent_name="Custom")
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    # --- root vs. nested ------------------------------------------------------

    def test_root_node_kept(self):
        run = _node_run("graph", parent_run_id=None)
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    def test_nested_node_with_agent_name_kept(self):
        run = _node_run("flight", parent_run_id=uuid4(), agent_name="Flight_Specialist")
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    def test_nested_node_with_agent_type_kept(self):
        run = _node_run("hotel", parent_run_id=uuid4(), agent_type="Hotel_Specialist")
        self.assertFalse(self.tracer._should_ignore_langgraph_node(run))

    def test_nested_identityless_node_ignored(self):
        # create_agent's internal ``model`` / ``tools`` nodes have no identity.
        run = _node_run("model", parent_run_id=uuid4())
        self.assertTrue(self.tracer._should_ignore_langgraph_node(run))


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

    def test_metadata_agent_name_wins_over_langgraph_node(self):
        """A node that advertises its own ``agent_name`` keeps that friendly
        label instead of the raw LangGraph structural node name.  This locks
        in the deliberate divergence from langchain-azure (which prefers the
        ``langgraph_node`` name) so nested sub-agents render as e.g.
        ``Flight_Specialist`` rather than ``flight``."""
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "flight", "agent_name": "Flight_Specialist"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "Flight_Specialist")

    def test_metadata_agent_type_wins_over_langgraph_node(self):
        """``agent_type`` is also a stronger display signal than the raw
        ``langgraph_node`` name."""
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "hotel", "agent_type": "Hotel_Specialist"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "Hotel_Specialist")

    def test_langgraph_node_used_when_no_explicit_identity(self):
        """When a node carries only the framework-injected ``langgraph_node``
        and no explicit ``agent_name``/``agent_type``, that structural node
        name is used as the label."""
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "researcher"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "researcher")

    def test_langgraph_start_node_skipped(self):
        """The ``__start__`` entrypoint node name is never used as a label;
        resolution falls through to the next signal (here, none -> None)."""
        tracer, _, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "__start__"}},
        )
        self.assertIsNone(tracer._resolve_agent_name(run))

    def test_agent_name_wins_over_config(self):
        """Per-node ``agent_name`` takes precedence over the process-level
        config name, so sub-agents do not inherit the top-level agent's name."""
        tracer, _, _ = _make_tracer(agent_config={"agent_name": "Travel_Assistant"})
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "flight", "agent_name": "Flight_Specialist"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "Flight_Specialist")

    def test_langgraph_node_wins_over_config(self):
        """A genuine LangGraph node name is more specific than the inherited
        process-level config name."""
        tracer, _, _ = _make_tracer(agent_config={"agent_name": "Travel_Assistant"})
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "flight"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run), "flight")

    def test_nested_agent_ignores_config_name(self):
        """With ``use_config=False`` (nested sub-agents), the config name is
        not used as a fallback; the node's own metadata identity is returned."""
        tracer, _, _ = _make_tracer(agent_config={"agent_name": "Travel_Assistant"})
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "flight"}},
        )
        self.assertEqual(tracer._resolve_agent_name(run, use_config=False), "flight")

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
    def test_suppressed_instrumentation_skips(self, mock_ctx):
        mock_ctx.get_value.return_value = True
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(run_type="chain", name="test")
        tracer._start_trace(run)
        otel_tracer.start_span.assert_not_called()

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_langgraph_node_span_uses_friendly_agent_name(self, mock_ctx):
        """A LangGraph node that carries its own ``agent_name`` emits an
        ``invoke_agent`` span named with that friendly label, not the raw
        structural node name (``flight``)."""
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, mock_span = _make_tracer(agent_config={"agent_name": "Travel_Assistant"})
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "flight", "agent_name": "Flight_Specialist"}},
        )
        tracer._start_trace(run)
        otel_tracer.start_span.assert_called_once()
        span_name = otel_tracer.start_span.call_args.kwargs["name"]
        self.assertEqual(span_name, f"{INVOKE_AGENT_OPERATION_NAME} Flight_Specialist")
        mock_span.set_attribute.assert_any_call(GEN_AI_AGENT_NAME_KEY, "Flight_Specialist")  # pylint: disable=no-member

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_langgraph_node_span_falls_back_to_node_name(self, mock_ctx):
        """A LangGraph node with no explicit ``agent_name`` uses the raw
        structural node name as its ``invoke_agent`` span label."""
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"langgraph_node": "researcher"}},
        )
        tracer._start_trace(run)
        otel_tracer.start_span.assert_called_once()
        span_name = otel_tracer.start_span.call_args.kwargs["name"]
        self.assertEqual(span_name, f"{INVOKE_AGENT_OPERATION_NAME} researcher")

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_suppressed_langgraph_node_emits_no_span(self, mock_ctx):
        """An identity-less internal node (create_agent's ``model``) is
        suppressed in ``_start_trace`` and produces no span, but is still
        registered in ``run_map`` so its children can be re-parented."""
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            parent_run_id=uuid4(),
            extra={"metadata": {"langgraph_node": "model"}},
        )
        tracer._start_trace(run)
        otel_tracer.start_span.assert_not_called()
        self.assertNotIn(run.id, tracer._spans_by_run)
        self.assertIn(str(run.id), tracer.run_map)

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_suppressed_start_node_emits_no_span(self, mock_ctx):
        """The ``__start__`` entrypoint node never produces a span."""
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        run = _make_run(
            run_type="chain",
            name="LangGraph",
            parent_run_id=uuid4(),
            extra={"metadata": {"langgraph_node": "__start__"}},
        )
        tracer._start_trace(run)
        otel_tracer.start_span.assert_not_called()

    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_suppressed_node_child_reparents_to_agent_span(self, mock_ctx):
        """A child of a suppressed node parents under the nearest real span
        (the enclosing agent), skipping the span-less internal node."""
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        agent_span = MagicMock(name="agent")
        child_span = MagicMock(name="child")
        otel_tracer.start_span.side_effect = [agent_span, child_span]

        # Real agent root span.
        agent_run = _make_run(
            run_type="chain",
            name="LangGraph",
            extra={"metadata": {"agent_name": "Travel_Assistant"}},
        )
        tracer._start_trace(agent_run)

        # Suppressed internal node between agent and the LLM child.
        model_node = _make_run(
            run_type="chain",
            name="LangGraph",
            parent_run_id=agent_run.id,
            extra={"metadata": {"langgraph_node": "model"}},
        )
        tracer._start_trace(model_node)

        # LLM child whose direct parent is the suppressed node.
        llm_run = _make_run(run_type="llm", name="gpt-4", parent_run_id=model_node.id)
        with patch("microsoft.opentelemetry._genai._langchain._tracer.trace_api.set_span_in_context") as mock_sic:
            tracer._start_trace(llm_run)
            # The child must be parented under the agent span, not the
            # span-less ``model`` node.
            self.assertIs(mock_sic.call_args_list[0][0][0], agent_span)


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
        _update_span(span, run, False)
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
        result = _update_span(span, run, False)
        self.assertIsNotNone(result)

    def test_chain_run_returns_none(self):
        span = MagicMock()
        run = _make_run(run_type="chain", name="test")
        result = _update_span(span, run, False)
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
        _update_span(span, run, False)
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

        _update_span(span, run, False)

        merged_attrs = {}
        for call in span.set_attributes.call_args_list:
            if call.args and isinstance(call.args[0], dict):
                merged_attrs.update(call.args[0])

        self.assertEqual(merged_attrs.get(GEN_AI_PROVIDER_NAME_KEY), "openai")
        self.assertEqual(merged_attrs.get(GEN_AI_REQUEST_CHOICE_COUNT_KEY), 2)

    @patch("microsoft.opentelemetry._genai._langchain._tracer._should_capture_content_on_spans", return_value=True)
    def test_llm_span_sets_messages_when_content_capture_enabled(self, _mock_capture):
        from langchain_core.messages import HumanMessage

        span = MagicMock()
        run = _make_run(
            run_type="chat_model",
            name="gpt-4o",
            inputs={"messages": [[HumanMessage(content="hi")]]},
            outputs={
                "llm_output": {"model_name": "gpt-4o"},
                "generations": [[{"message": {"content": "hello there"}}]],
            },
            extra=None,
        )

        _update_span(span, run, enable_sensitive_data=True)

        set_attr_keys = {call.args[0] for call in span.set_attribute.call_args_list if call.args}  # pylint: disable=no-member
        self.assertIn(GEN_AI_INPUT_MESSAGES_KEY, set_attr_keys)
        self.assertIn(GEN_AI_OUTPUT_MESSAGES_KEY, set_attr_keys)

    @patch("microsoft.opentelemetry._genai._langchain._tracer._should_capture_content_on_spans", return_value=False)
    def test_llm_span_skips_messages_when_content_capture_disabled(self, _mock_capture):
        from langchain_core.messages import HumanMessage

        span = MagicMock()
        run = _make_run(
            run_type="chat_model",
            name="gpt-4o",
            inputs={"messages": [[HumanMessage(content="hi")]]},
            outputs={
                "llm_output": {"model_name": "gpt-4o"},
                "generations": [[{"message": {"content": "hello there"}}]],
            },
            extra=None,
        )

        _update_span(span, run, enable_sensitive_data=False)

        set_attr_keys = {call.args[0] for call in span.set_attribute.call_args_list if call.args}  # pylint: disable=no-member
        self.assertNotIn(GEN_AI_INPUT_MESSAGES_KEY, set_attr_keys)
        self.assertNotIn(GEN_AI_OUTPUT_MESSAGES_KEY, set_attr_keys)


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


class TestAggregateExcludesStructuredOutput(TestCase):
    @patch("microsoft.opentelemetry._genai._langchain._tracer.context_api")
    def test_structured_output_llm_excluded_from_transcript(self, mock_ctx):
        mock_ctx.get_value.return_value = None
        tracer, otel_tracer, _ = _make_tracer()
        wrapper = MagicMock()
        inner = MagicMock()
        otel_tracer.start_span.side_effect = [wrapper, inner]

        agent_run = _make_run(
            run_type="chain",
            name="LangGraph",
            inputs={"messages": [{"role": "user", "content": "What is 2+2?"}]},
        )
        tracer.run_map[str(agent_run.id)] = agent_run
        tracer._start_trace(agent_run)

        triage_llm = _make_run(
            run_type="chat_model",
            name="gpt-4.1",
            parent_run_id=agent_run.id,
            inputs={"prompts": ["System: route this\nHuman: What is 2+2?"]},
            extra={
                "options": {
                    "ls_structured_output_format": {
                        "kwargs": {"method": "json_schema"},
                        "schema": {"type": "object"},
                    }
                }
            },
            outputs={
                "generations": [
                    [
                        {
                            "text": '{"destination":"math"}',
                            "message": {
                                "id": ["langchain", "schema", "messages", "AIMessage"],
                                "kwargs": {
                                    "content": '{"destination":"math"}',
                                    "type": "ai",
                                },
                            },
                        }
                    ]
                ]
            },
        )
        tracer.run_map[str(triage_llm.id)] = triage_llm
        tracer._aggregate_into_parent(triage_llm)

        answer_llm = _make_run(
            run_type="chat_model",
            name="gpt-4.1",
            parent_run_id=agent_run.id,
            inputs={"prompts": ["Human: What is 2+2?"]},
            extra=None,
            outputs={
                "generations": [
                    [
                        {
                            "text": "4",
                            "message": {
                                "id": ["langchain", "schema", "messages", "AIMessage"],
                                "kwargs": {"content": "4", "type": "ai"},
                            },
                        }
                    ]
                ]
            },
        )
        tracer.run_map[str(answer_llm.id)] = answer_llm
        tracer._aggregate_into_parent(answer_llm)

        content = tracer._agent_content[agent_run.id]

        roles = [m.role for m in content["input_messages"]]
        self.assertEqual(roles, ["user"])
        transcript_text = "".join(
            part.content for m in content["input_messages"] for part in m.parts if getattr(part, "content", None)
        )
        self.assertNotIn("destination", transcript_text)
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


# ---- LangChainTracer enable_sensitive_data -----------------------------------


class TestLangChainTracerEnableSensitiveData(TestCase):
    def test_default_enable_sensitive_data_is_false(self):
        tracer, _, _ = _make_tracer()
        self.assertFalse(tracer._enable_sensitive_data)

    def test_enable_sensitive_data_stored_when_true(self):
        otel_tracer = MagicMock()
        tracer = LangChainTracer(
            otel_tracer,
            False,
            enable_sensitive_data=True,
        )
        self.assertTrue(tracer._enable_sensitive_data)

    def test_enable_sensitive_data_stored_when_false(self):
        otel_tracer = MagicMock()
        tracer = LangChainTracer(
            otel_tracer,
            False,
            enable_sensitive_data=False,
        )
        self.assertFalse(tracer._enable_sensitive_data)
