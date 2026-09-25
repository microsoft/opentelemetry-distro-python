# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# pylint: disable=no-member

"""Tests for GenAIMainAgentSpanProcessor."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from microsoft.opentelemetry._constants import (
    GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY,
    GEN_AI_MAIN_AGENT_ID_KEY,
    GEN_AI_MAIN_AGENT_NAME_KEY,
    GEN_AI_MAIN_AGENT_VERSION_KEY,
    GEN_AI_PROJECT_ID_KEYS,
)
from microsoft.opentelemetry._genai.main_agent._processor import (
    GenAIMainAgentSpanProcessor,
)
from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_AGENT_ID_KEY,
    GEN_AI_AGENT_NAME_KEY,
    GEN_AI_AGENT_VERSION_KEY,
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)


def _mock_parent_span(attributes: dict, valid: bool = True) -> Mock:
    parent = Mock()
    parent.attributes = attributes
    span_context = Mock()
    span_context.is_valid = valid
    parent.get_span_context.return_value = span_context
    return parent


def _mock_invalid_parent_span() -> Mock:
    parent = Mock()
    span_context = Mock()
    span_context.is_valid = False
    parent.get_span_context.return_value = span_context
    return parent


class TestGenAIMainAgentSpanProcessorOnStart(unittest.TestCase):
    """on_start propagation from parent span to current span."""

    def setUp(self) -> None:
        self.processor = GenAIMainAgentSpanProcessor()
        self.span = MagicMock()

    def test_no_valid_parent_does_nothing(self):
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_invalid_parent_span(),
        ):
            self.processor.on_start(self.span, parent_context=None)

        self.span.set_attribute.assert_not_called()

    def test_parent_with_no_relevant_attributes_does_nothing(self):
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span({"unrelated": "value"}),
        ):
            self.processor.on_start(self.span, parent_context=None)

        self.span.set_attribute.assert_not_called()

    def test_parent_with_only_fallbacks_copies_fallbacks(self):
        parent_attrs = {
            GEN_AI_AGENT_NAME_KEY: "main",
            GEN_AI_AGENT_ID_KEY: "id-1",
            GEN_AI_AGENT_VERSION_KEY: "v1",
            GEN_AI_CONVERSATION_ID_KEY: "conv-1",
        }
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span(parent_attrs),
        ):
            self.processor.on_start(self.span, parent_context=None)

        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_NAME_KEY, "main")
        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_ID_KEY, "id-1")
        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_VERSION_KEY, "v1")
        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY, "conv-1")
        self.assertEqual(self.span.set_attribute.call_count, 4)

    def test_parent_with_primary_wins_over_fallback(self):
        parent_attrs = {
            GEN_AI_MAIN_AGENT_NAME_KEY: "primary",
            GEN_AI_AGENT_NAME_KEY: "fallback",
        }
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span(parent_attrs),
        ):
            self.processor.on_start(self.span, parent_context=None)

        self.span.set_attribute.assert_called_once_with(GEN_AI_MAIN_AGENT_NAME_KEY, "primary")

    def test_parent_with_mixed_primary_and_fallback(self):
        parent_attrs = {
            GEN_AI_MAIN_AGENT_NAME_KEY: "primary-name",
            GEN_AI_AGENT_ID_KEY: "fallback-id",
        }
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span(parent_attrs),
        ):
            self.processor.on_start(self.span, parent_context=None)

        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_NAME_KEY, "primary-name")
        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_ID_KEY, "fallback-id")
        self.assertEqual(self.span.set_attribute.call_count, 2)


class TestGenAIMainAgentSpanProcessorOnEnd(unittest.TestCase):
    """on_end self-copy when this span itself is the top-level invoke_agent."""

    def setUp(self) -> None:
        self.processor = GenAIMainAgentSpanProcessor()

    @staticmethod
    def _make_span(attributes: dict, *, has_internal_attrs: bool = True):
        """Build a mock ReadableSpan with context.span_id and _attributes."""
        span = MagicMock()
        span.attributes = dict(attributes)
        span.context.span_id = id(span)  # unique per mock
        if has_internal_attrs:
            span._attributes = dict(attributes)
        else:
            del span._attributes
        return span

    def test_skipped_when_not_invoke_agent(self):
        span = self._make_span({GEN_AI_OPERATION_NAME_KEY: "chat"})

        self.processor.on_end(span)

        # _attributes must remain unchanged
        self.assertNotIn(GEN_AI_MAIN_AGENT_NAME_KEY, span._attributes)

    def test_skipped_when_main_agent_attribute_already_present(self):
        span = self._make_span(
            {
                GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME,
                GEN_AI_MAIN_AGENT_NAME_KEY: "already-set",
                GEN_AI_AGENT_NAME_KEY: "self",
            }
        )

        self.processor.on_end(span)

        # Must keep the existing value, not overwrite with "self"
        self.assertEqual(span._attributes[GEN_AI_MAIN_AGENT_NAME_KEY], "already-set")

    def test_copies_self_attributes_when_invoke_agent_and_unenriched(self):
        span = self._make_span(
            {
                GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME,
                GEN_AI_AGENT_NAME_KEY: "self-name",
                GEN_AI_AGENT_ID_KEY: "self-id",
                GEN_AI_AGENT_VERSION_KEY: "self-v",
                GEN_AI_CONVERSATION_ID_KEY: "self-conv",
            }
        )

        self.processor.on_end(span)

        self.assertEqual(span._attributes[GEN_AI_MAIN_AGENT_NAME_KEY], "self-name")
        self.assertEqual(span._attributes[GEN_AI_MAIN_AGENT_ID_KEY], "self-id")
        self.assertEqual(span._attributes[GEN_AI_MAIN_AGENT_VERSION_KEY], "self-v")
        self.assertEqual(span._attributes[GEN_AI_MAIN_AGENT_CONVERSATION_ID_KEY], "self-conv")

    def test_copies_only_present_attributes(self):
        span = self._make_span(
            {
                GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME,
                GEN_AI_AGENT_NAME_KEY: "only-name",
            }
        )

        self.processor.on_end(span)

        self.assertEqual(span._attributes[GEN_AI_MAIN_AGENT_NAME_KEY], "only-name")
        self.assertNotIn(GEN_AI_MAIN_AGENT_ID_KEY, span._attributes)

    def test_noop_when_span_has_no_internal_attributes(self):
        # ReadableSpan-only objects without ``_attributes`` must not raise.
        span = self._make_span(
            {
                GEN_AI_OPERATION_NAME_KEY: INVOKE_AGENT_OPERATION_NAME,
                GEN_AI_AGENT_NAME_KEY: "self-name",
            },
            has_internal_attrs=False,
        )

        self.processor.on_end(span)  # must not raise


class TestGenAIMainAgentSpanProcessorLifecycle(unittest.TestCase):
    def test_shutdown_and_force_flush_are_noops(self):
        processor = GenAIMainAgentSpanProcessor()
        processor.shutdown()
        self.assertTrue(processor.force_flush())


class TestGenAIMainAgentSpanProcessorProjectIdOnStart(unittest.TestCase):
    """on_start copies Foundry project-id attributes from parent to child."""

    PROJECT_ID = "/subscriptions/sub/resourceGroups/rg/providers/x/projects/p"

    def setUp(self) -> None:
        self.processor = GenAIMainAgentSpanProcessor()
        self.span = MagicMock()

    def test_copies_project_id_keys_from_parent(self):
        parent_attrs = {key: self.PROJECT_ID for key in GEN_AI_PROJECT_ID_KEYS}
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span(parent_attrs),
        ):
            self.processor.on_start(self.span, parent_context=None)

        for key in GEN_AI_PROJECT_ID_KEYS:
            self.span.set_attribute.assert_any_call(key, self.PROJECT_ID)

    def test_copies_project_id_alongside_main_agent_attrs(self):
        parent_attrs = {GEN_AI_AGENT_NAME_KEY: "main"}
        parent_attrs.update({key: self.PROJECT_ID for key in GEN_AI_PROJECT_ID_KEYS})
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span(parent_attrs),
        ):
            self.processor.on_start(self.span, parent_context=None)

        self.span.set_attribute.assert_any_call(GEN_AI_MAIN_AGENT_NAME_KEY, "main")
        for key in GEN_AI_PROJECT_ID_KEYS:
            self.span.set_attribute.assert_any_call(key, self.PROJECT_ID)

    def test_no_project_id_keys_when_parent_unstamped(self):
        with patch(
            "microsoft.opentelemetry._genai.main_agent._processor.trace.get_current_span",
            return_value=_mock_parent_span({GEN_AI_AGENT_NAME_KEY: "main"}),
        ):
            self.processor.on_start(self.span, parent_context=None)

        for key in GEN_AI_PROJECT_ID_KEYS:
            for call in self.span.set_attribute.call_args_list:
                self.assertNotEqual(call.args[0], key)


class TestGenAIMainAgentSpanProcessorProjectIdOnEnd(unittest.TestCase):
    """on_end recovers project-id attributes from the parent when on_start
    missed them (parent stamped after the child was created)."""

    PROJECT_ID = "/subscriptions/sub/resourceGroups/rg/providers/x/projects/p"

    def setUp(self) -> None:
        self.processor = GenAIMainAgentSpanProcessor()

    @staticmethod
    def _make_span(attributes: dict):
        span = MagicMock()
        span.attributes = dict(attributes)
        span.context.span_id = id(span)
        span._attributes = dict(attributes)
        return span

    def test_recovers_project_id_from_parent_on_end(self):
        parent = _mock_parent_span({key: self.PROJECT_ID for key in GEN_AI_PROJECT_ID_KEYS})
        span = self._make_span({GEN_AI_OPERATION_NAME_KEY: "chat"})

        self.processor._parent_spans[span.context.span_id] = parent

        self.processor.on_end(span)

        for key in GEN_AI_PROJECT_ID_KEYS:
            self.assertEqual(span._attributes[key], self.PROJECT_ID)

    def test_does_not_overwrite_existing_project_id(self):
        parent = _mock_parent_span({key: "parent-value" for key in GEN_AI_PROJECT_ID_KEYS})
        span = self._make_span(
            {
                GEN_AI_OPERATION_NAME_KEY: "chat",
                **{key: self.PROJECT_ID for key in GEN_AI_PROJECT_ID_KEYS},
            }
        )
        self.processor._parent_spans[span.context.span_id] = parent

        self.processor.on_end(span)

        for key in GEN_AI_PROJECT_ID_KEYS:
            self.assertEqual(span._attributes[key], self.PROJECT_ID)

    def test_no_project_id_when_parent_unstamped(self):
        parent = _mock_parent_span({GEN_AI_AGENT_NAME_KEY: "main"})
        span = self._make_span({GEN_AI_OPERATION_NAME_KEY: "chat"})
        self.processor._parent_spans[span.context.span_id] = parent

        self.processor.on_end(span)

        for key in GEN_AI_PROJECT_ID_KEYS:
            self.assertNotIn(key, span._attributes)
