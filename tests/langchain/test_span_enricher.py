# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for LangChain span enricher."""

import unittest
from unittest.mock import Mock

from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_CONVERSATION_ID_KEY,
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
    GEN_AI_TOOL_ARGS_KEY,
    GEN_AI_TOOL_CALL_RESULT_KEY,
    SESSION_ID_KEY,
)
from microsoft.opentelemetry._genai._langchain._span_enricher import enrich_langchain_span


class TestLangChainSpanEnricher(unittest.TestCase):
    """Test suite for enrich_langchain_span function."""

    def test_maps_conversation_id_to_session_id(self):
        """gen_ai.conversation.id is mapped to microsoft.session.id."""
        span = Mock()
        span.name = "chat gpt-4o"
        span.attributes = {
            GEN_AI_CONVERSATION_ID_KEY: "conv-123",
        }

        result = enrich_langchain_span(span)

        assert result.attributes is not None
        self.assertEqual(result.attributes[SESSION_ID_KEY], "conv-123")

    def test_does_not_overwrite_existing_session_id(self):
        """If microsoft.session.id is already present, don't overwrite."""
        span = Mock()
        span.name = "chat gpt-4o"
        span.attributes = {
            GEN_AI_CONVERSATION_ID_KEY: "conv-123",
            SESSION_ID_KEY: "existing-session",
        }

        result = enrich_langchain_span(span)
        # Should return original span unchanged
        self.assertEqual(result, span)

    def test_invoke_agent_span_enrichment(self):
        """invoke_agent spans pass through input/output messages."""
        span = Mock()
        span.name = "invoke_agent Travel_Assistant"
        span.attributes = {
            GEN_AI_INPUT_MESSAGES_KEY: '["Where should I go?"]',
            GEN_AI_OUTPUT_MESSAGES_KEY: '["Try Barcelona!"]',
        }

        result = enrich_langchain_span(span)

        assert result.attributes is not None
        self.assertEqual(result.attributes[GEN_AI_INPUT_MESSAGES_KEY], '["Where should I go?"]')
        self.assertEqual(result.attributes[GEN_AI_OUTPUT_MESSAGES_KEY], '["Try Barcelona!"]')

    def test_invoke_agent_with_conversation_id(self):
        """invoke_agent spans get both session_id mapping and message enrichment."""
        span = Mock()
        span.name = "invoke_agent MyAgent"
        span.attributes = {
            GEN_AI_CONVERSATION_ID_KEY: "conv-456",
            GEN_AI_INPUT_MESSAGES_KEY: '["Hello"]',
        }

        result = enrich_langchain_span(span)

        assert result.attributes is not None
        self.assertEqual(result.attributes[SESSION_ID_KEY], "conv-456")
        self.assertEqual(result.attributes[GEN_AI_INPUT_MESSAGES_KEY], '["Hello"]')

    def test_execute_tool_span_enrichment(self):
        """execute_tool spans map tool arguments and results."""
        span = Mock()
        span.name = "execute_tool get_weather"
        span.attributes = {
            GEN_AI_TOOL_ARGS_KEY: '{"city": "Barcelona"}',
            GEN_AI_TOOL_CALL_RESULT_KEY: "Sunny, 25C",
        }

        result = enrich_langchain_span(span)

        assert result.attributes is not None
        self.assertEqual(result.attributes[GEN_AI_TOOL_ARGS_KEY], '{"city": "Barcelona"}')
        self.assertEqual(result.attributes[GEN_AI_TOOL_CALL_RESULT_KEY], "Sunny, 25C")

    def test_non_matching_span_returns_original(self):
        """Non-matching spans without conversation_id return unchanged."""
        span = Mock()
        span.name = "other_operation"
        span.attributes = {"key": "value"}

        self.assertEqual(enrich_langchain_span(span), span)

    def test_none_attributes_returns_original(self):
        """Spans with None attributes return unchanged."""
        span = Mock()
        span.name = "invoke_agent Test"
        span.attributes = None

        self.assertEqual(enrich_langchain_span(span), span)

    def test_empty_attributes_returns_original(self):
        """Spans with empty attributes return unchanged."""
        span = Mock()
        span.name = "invoke_agent Test"
        span.attributes = {}

        self.assertEqual(enrich_langchain_span(span), span)
