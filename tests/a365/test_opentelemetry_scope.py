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
