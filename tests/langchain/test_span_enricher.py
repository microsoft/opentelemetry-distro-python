# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for LangChain span enricher."""

import json
import unittest
from unittest.mock import Mock

from microsoft.opentelemetry.a365.core.constants import (
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OUTPUT_MESSAGES_KEY,
)
from microsoft.opentelemetry.a365.core.enricher_utils import (
    extract_content_as_string_list,
)
from microsoft.opentelemetry.a365.langchain._span_enricher import (
    enrich_langchain_span,
)


class TestExtractContentAsStringList(unittest.TestCase):
    """Tests for the shared extract_content_as_string_list helper."""

    def test_structured_messages_to_plain_strings(self):
        messages = json.dumps(
            [
                {"role": "user", "parts": [{"type": "text", "content": "Hello"}]},
            ]
        )
        result = json.loads(extract_content_as_string_list(messages))
        self.assertEqual(result, ["Hello"])

    def test_filters_by_role(self):
        messages = json.dumps(
            [
                {"role": "system", "parts": [{"type": "text", "content": "You are helpful"}]},
                {"role": "user", "parts": [{"type": "text", "content": "Hello"}]},
            ]
        )
        result = json.loads(extract_content_as_string_list(messages, role_filter="user"))
        self.assertEqual(result, ["Hello"])

    def test_no_role_filter_extracts_all(self):
        messages = json.dumps(
            [
                {"role": "system", "parts": [{"type": "text", "content": "You are helpful"}]},
                {"role": "user", "parts": [{"type": "text", "content": "Hello"}]},
            ]
        )
        result = json.loads(extract_content_as_string_list(messages))
        self.assertEqual(result, ["You are helpful", "Hello"])

    def test_skips_non_text_parts(self):
        messages = json.dumps(
            [
                {
                    "role": "assistant",
                    "parts": [
                        {"type": "tool_call", "id": "c1"},
                        {"type": "text", "content": "Result is 3"},
                    ],
                },
            ]
        )
        result = json.loads(extract_content_as_string_list(messages, role_filter="assistant"))
        self.assertEqual(result, ["Result is 3"])

    def test_invalid_json_returns_original(self):
        self.assertEqual(extract_content_as_string_list("not json"), "not json")

    def test_non_list_returns_original(self):
        self.assertEqual(extract_content_as_string_list('"just a string"'), '"just a string"')

    def test_plain_string_list_returns_original(self):
        original = '["hi", "there"]'
        self.assertEqual(extract_content_as_string_list(original), original)


class TestEnrichLangchainSpan(unittest.TestCase):
    """Tests for enrich_langchain_span."""

    def test_invoke_agent_converts_structured_to_plain(self):
        span = Mock()
        span.name = "invoke_agent my_agent"
        span.attributes = {
            GEN_AI_INPUT_MESSAGES_KEY: json.dumps(
                [
                    {"role": "user", "parts": [{"type": "text", "content": "What is 2+2?"}]},
                ]
            ),
            GEN_AI_OUTPUT_MESSAGES_KEY: json.dumps(
                [
                    {"role": "assistant", "parts": [{"type": "text", "content": "4"}], "finish_reason": "stop"},
                ]
            ),
        }

        result = enrich_langchain_span(span)

        assert result.attributes is not None
        self.assertEqual(result.attributes[GEN_AI_INPUT_MESSAGES_KEY], '["What is 2+2?"]')
        self.assertEqual(result.attributes[GEN_AI_OUTPUT_MESSAGES_KEY], '["4"]')

    def test_invoke_agent_filters_roles(self):
        """Input filters for user, output filters for assistant."""
        span = Mock()
        span.name = "invoke_agent test"
        span.attributes = {
            GEN_AI_INPUT_MESSAGES_KEY: json.dumps(
                [
                    {"role": "system", "parts": [{"type": "text", "content": "System prompt"}]},
                    {"role": "user", "parts": [{"type": "text", "content": "Hello"}]},
                ]
            ),
            GEN_AI_OUTPUT_MESSAGES_KEY: json.dumps(
                [
                    {"role": "tool", "parts": [{"type": "text", "content": "tool result"}]},
                    {"role": "assistant", "parts": [{"type": "text", "content": "Answer"}]},
                ]
            ),
        }

        result = enrich_langchain_span(span)

        assert result.attributes is not None
        self.assertEqual(result.attributes[GEN_AI_INPUT_MESSAGES_KEY], '["Hello"]')
        self.assertEqual(result.attributes[GEN_AI_OUTPUT_MESSAGES_KEY], '["Answer"]')

    def test_non_invoke_agent_span_unchanged(self):
        span = Mock()
        span.name = "chat gpt-4"
        span.attributes = {
            GEN_AI_INPUT_MESSAGES_KEY: "some value",
        }

        self.assertIs(enrich_langchain_span(span), span)

    def test_no_attributes_returns_original(self):
        span = Mock()
        span.name = "invoke_agent test"
        span.attributes = None

        self.assertIs(enrich_langchain_span(span), span)

    def test_empty_attributes_returns_original(self):
        span = Mock()
        span.name = "invoke_agent test"
        span.attributes = {}

        self.assertIs(enrich_langchain_span(span), span)


if __name__ == "__main__":
    unittest.main()
