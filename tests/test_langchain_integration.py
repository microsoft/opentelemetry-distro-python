# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Integration tests for LangChain instrumentation.

Validates that the in-repo ``LangChainInstrumentor`` can be loaded, activated,
and that it monkey-patches LangChain's callback machinery.  Also validates
that ``agent_name`` / ``agent_id`` kwargs are forwarded correctly.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("langchain_core")

# pylint: disable=wrong-import-position
from microsoft.opentelemetry._genai._langchain._tracer_instrumentor import (  # noqa: E402
    LangChainInstrumentor,
)

from microsoft.opentelemetry._constants import (  # noqa: E402
    _SUPPORTED_INSTRUMENTED_LIBRARIES,
    _OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT_ENV,
    _OTEL_SEMCONV_STABILITY_OPT_IN_ENV,
)

# pylint: enable=wrong-import-position


class TestLangChainInstrumentationConfig(unittest.TestCase):
    """Verify langchain is registered in the distro's supported library lists."""

    def test_langchain_in_supported_libraries(self):
        self.assertIn("langchain", _SUPPORTED_INSTRUMENTED_LIBRARIES)


class TestLangChainInstrumentorLifecycle(unittest.TestCase):
    """Verify the LangChainInstrumentor can be activated and torn down."""

    def setUp(self):
        self.instrumentor = LangChainInstrumentor()
        if self.instrumentor.is_instrumented_by_opentelemetry:
            self.instrumentor._uninstrument()

    def tearDown(self):
        inst = LangChainInstrumentor()
        if inst.is_instrumented_by_opentelemetry:
            inst._uninstrument()

    def test_instrumentation_dependencies(self):
        deps = self.instrumentor.instrumentation_dependencies()
        self.assertIn("langchain-core >= 0.2.0", deps)

    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.get_otel_logger")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.trace_api.get_tracer")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.wrap_function_wrapper")
    def test_instrument_creates_tracer(self, mock_wrap, mock_get_tracer, mock_get_logger):
        mock_get_tracer.return_value = MagicMock()
        mock_get_logger.return_value = MagicMock()
        self.instrumentor._instrument()
        mock_get_tracer.assert_called_once()
        self.assertIsNotNone(self.instrumentor._tracer)

    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.get_otel_logger")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.trace_api.get_tracer")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.wrap_function_wrapper")
    def test_uninstrument_clears_tracer(self, mock_wrap, mock_get_tracer, mock_get_logger):
        mock_get_tracer.return_value = MagicMock()
        mock_get_logger.return_value = MagicMock()
        self.instrumentor._instrument()
        self.assertIsNotNone(self.instrumentor._tracer)
        self.instrumentor._uninstrument()
        self.assertIsNone(self.instrumentor._tracer)


class TestLangChainKwargsForwarding(unittest.TestCase):
    """Verify that agent_name / agent_id kwargs flow to the tracer."""

    def setUp(self):
        inst = LangChainInstrumentor()
        if inst.is_instrumented_by_opentelemetry:
            inst._uninstrument()

    def tearDown(self):
        inst = LangChainInstrumentor()
        if inst.is_instrumented_by_opentelemetry:
            inst._uninstrument()

    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.get_otel_logger")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.trace_api.get_tracer")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.wrap_function_wrapper")
    def test_agent_name_forwarded(self, mock_wrap, mock_get_tracer, mock_get_logger):
        """agent_name passed to _instrument() reaches the tracer's agent_config."""
        mock_get_tracer.return_value = MagicMock()
        mock_get_logger.return_value = MagicMock()
        inst = LangChainInstrumentor()
        inst._instrument(agent_name="TestBot", agent_id="a-1")
        self.assertEqual(inst._tracer._agent_config["agent_name"], "TestBot")
        self.assertEqual(inst._tracer._agent_config["agent_id"], "a-1")

    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.get_otel_logger")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.trace_api.get_tracer")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.wrap_function_wrapper")
    def test_separate_trace_kwarg_forwarded(self, mock_wrap, mock_get_tracer, mock_get_logger):
        """separate_trace_from_runtime_context reaches the tracer."""
        mock_get_tracer.return_value = MagicMock()
        mock_get_logger.return_value = MagicMock()
        inst = LangChainInstrumentor()
        inst._instrument(separate_trace_from_runtime_context=True)
        self.assertTrue(inst._tracer._separate_trace_from_runtime_context)


class TestLangChainCallbackPatching(unittest.TestCase):
    """Verify the instrumentor patches LangChain's BaseCallbackManager."""

    def setUp(self):
        inst = LangChainInstrumentor()
        if inst.is_instrumented_by_opentelemetry:
            inst._uninstrument()

    def tearDown(self):
        inst = LangChainInstrumentor()
        if inst.is_instrumented_by_opentelemetry:
            inst._uninstrument()

    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.get_otel_logger")
    @patch("microsoft.opentelemetry._genai._langchain._tracer_instrumentor.trace_api.get_tracer")
    def test_callback_manager_patched(self, mock_get_tracer, mock_get_logger):
        """After _instrument(), BaseCallbackManager.__init__ is wrapped."""
        mock_get_tracer.return_value = MagicMock()
        mock_get_logger.return_value = MagicMock()
        inst = LangChainInstrumentor()
        inst._instrument()

        from langchain_core.callbacks import CallbackManager  # noqa: F811 pylint: disable=unused-import

        # After instrumentation, creating a new CallbackManager should include
        # the OTel tracer in its handlers (or the __init__ should be wrapped).
        # We verify by checking the instrumentor recorded the original init.
        self.assertIsNotNone(inst._original_cb_init)


class TestLangChainCaptureMessageContentWiring(unittest.TestCase):
    """Verify the ``capture_message_content`` + ``enable_experimental_mode``
    kwargs propagate to the env vars that LangChain content-capture reads.

    This guards against regressions where the kwargs are dropped on the floor
    instead of being written to ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT``
    and ``OTEL_SEMCONV_STABILITY_OPT_IN``, which together are what
    ``_should_capture_content_on_spans()`` reads (via upstream
    ``is_experimental_mode()`` and ``get_content_capturing_mode()``).
    """

    _CONTENT_ENV = _OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT_ENV
    _STABILITY_ENV = _OTEL_SEMCONV_STABILITY_OPT_IN_ENV

    def setUp(self):
        self._saved_content = os.environ.pop(self._CONTENT_ENV, None)
        self._saved_stability = os.environ.pop(self._STABILITY_ENV, None)

    def tearDown(self):
        os.environ.pop(self._CONTENT_ENV, None)
        os.environ.pop(self._STABILITY_ENV, None)
        if self._saved_content is not None:
            os.environ[self._CONTENT_ENV] = self._saved_content
        if self._saved_stability is not None:
            os.environ[self._STABILITY_ENV] = self._saved_stability

    @patch("microsoft.opentelemetry._distro._append_azure_monitor_components", return_value=(None, None, None))
    def test_kwargs_set_env_vars_read_by_langchain(self, _append_mock):
        from microsoft.opentelemetry._distro import use_microsoft_opentelemetry

        use_microsoft_opentelemetry(
            enable_experimental_mode=True,
            capture_message_content="span_and_event",
        )

        self.assertEqual(os.environ.get(self._CONTENT_ENV), "span_and_event")
        self.assertEqual(os.environ.get(self._STABILITY_ENV), "gen_ai_latest_experimental")

    @patch("microsoft.opentelemetry._distro._append_azure_monitor_components", return_value=(None, None, None))
    def test_unrecognised_kwarg_leaves_content_env_unset(self, _append_mock):
        from microsoft.opentelemetry._distro import use_microsoft_opentelemetry

        use_microsoft_opentelemetry(
            enable_experimental_mode=True,
            capture_message_content="banana",
        )

        self.assertNotIn(self._CONTENT_ENV, os.environ)

    @patch("microsoft.opentelemetry._distro._append_azure_monitor_components", return_value=(None, None, None))
    def test_capture_kwarg_without_experimental_mode_is_a_noop(self, _append_mock):
        from microsoft.opentelemetry._distro import use_microsoft_opentelemetry

        use_microsoft_opentelemetry(capture_message_content="span_and_event")

        self.assertNotIn(self._CONTENT_ENV, os.environ)
        self.assertNotIn(self._STABILITY_ENV, os.environ)

    def test_langchain_helper_reads_same_env_var(self):
        """Sanity-check that the LangChain content-capture helper looks at the
        env var our distro writes — not some other key. ``is_experimental_mode``
        is patched so the test doesn't depend on cached upstream stability state."""
        from opentelemetry.util.genai import utils as _genai_utils  # type: ignore[import-not-found]
        from opentelemetry.util.genai.utils import (  # type: ignore[import-not-found]
            ContentCapturingMode,
            get_content_capturing_mode,
        )

        os.environ[self._CONTENT_ENV] = "span_and_event"
        with patch.object(_genai_utils, "is_experimental_mode", return_value=True):
            self.assertEqual(get_content_capturing_mode(), ContentCapturingMode.SPAN_AND_EVENT)


if __name__ == "__main__":
    unittest.main()
