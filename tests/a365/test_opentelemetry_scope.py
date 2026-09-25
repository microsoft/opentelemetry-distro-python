# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from unittest.mock import MagicMock, patch

from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope


class TestOpenTelemetryScopeRecordAttributes(unittest.TestCase):
    """Verify record_attributes preserves existing and earlier span attributes."""

    def _make_scope(self):
        mock_span = MagicMock()
        mock_span.attributes = {}
        mock_span.get_span_context.return_value = MagicMock(span_id=0x1234)

        def set_attribute(name, value):
            mock_span.attributes[name] = value

        mock_span.set_attribute.side_effect = set_attribute
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        with patch.object(OpenTelemetryScope, "_get_tracer", return_value=mock_tracer):
            scope = OpenTelemetryScope(operation_name="invoke_agent", activity_name="test_activity")

        return scope, mock_span

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_preserves_existing_span_attributes(self):
        scope, span = self._make_scope()

        scope.record_attributes(
            {
                "gen_ai.operation.name": "malicious_override",
                "custom.key": "custom-value",
            }
        )

        self.assertEqual(span.attributes["gen_ai.operation.name"], "invoke_agent")
        self.assertEqual(span.attributes["custom.key"], "custom-value")

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_preserves_baggage_attribute_added_at_span_start(self):
        scope, span = self._make_scope()
        span.attributes["customer.tier"] = "gold"

        scope.record_attributes({"customer.tier": "override"})

        self.assertEqual(span.attributes["customer.tier"], "gold")

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_preserves_first_duplicate_from_iterable(self):
        scope, span = self._make_scope()

        scope.record_attributes(
            (
                ("custom.key", "first"),
                ("custom.key", "second"),
            )
        )

        self.assertEqual(span.attributes["custom.key"], "first")

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_preserves_attribute_from_earlier_call(self):
        scope, span = self._make_scope()

        scope.record_attributes({"custom.key": "first"})
        scope.record_attributes({"custom.key": "second"})

        self.assertEqual(span.attributes["custom.key"], "first")

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_retries_key_when_span_rejects_first_value(self):
        scope, span = self._make_scope()

        def set_attribute(name, value):
            if value is not None:
                span.attributes[name] = value

        span.set_attribute.side_effect = set_attribute

        scope.record_attributes(
            (
                ("custom.key", None),
                ("custom.key", "accepted"),
            )
        )

        self.assertEqual(span.attributes["custom.key"], "accepted")

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_supports_recording_span_without_attributes_property(self):
        mock_span = MagicMock(
            spec_set=[
                "get_span_context",
                "is_recording",
                "set_attribute",
            ]
        )
        mock_span.get_span_context.return_value = MagicMock(span_id=0x1234)
        mock_span.is_recording.return_value = True
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        with patch.object(OpenTelemetryScope, "_get_tracer", return_value=mock_tracer):
            scope = OpenTelemetryScope(operation_name="invoke_agent", activity_name="test_activity")

        scope.record_attributes(
            (
                ("gen_ai.operation.name", "override"),
                ("custom.key", "first"),
                ("custom.key", "second"),
            )
        )

        custom_calls = [call for call in mock_span.set_attribute.call_args_list if call.args[0] == "custom.key"]
        self.assertEqual(len(custom_calls), 1)
        self.assertEqual(custom_calls[0].args[1], "first")

    @patch.dict(os.environ, {"ENABLE_OBSERVABILITY": "true"}, clear=True)
    def test_ignores_blank_keys(self):
        scope, span = self._make_scope()

        scope.record_attributes(
            [
                ("", "ignored"),
                ("   ", "ignored-too"),
                ("custom.key", "custom-value"),
            ]
        )

        self.assertNotIn("", span.attributes)
        self.assertNotIn("   ", span.attributes)
        self.assertEqual(span.attributes["custom.key"], "custom-value")


if __name__ == "__main__":
    unittest.main()
