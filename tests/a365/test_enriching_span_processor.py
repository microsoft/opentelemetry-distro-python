# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import logging
import multiprocessing
import os
import threading
import time
import unittest
from typing import List, Set
from unittest import mock
from unittest.mock import MagicMock

from opentelemetry.sdk.environment_variables import (
    OTEL_BSP_EXPORT_TIMEOUT,
    OTEL_BSP_MAX_EXPORT_BATCH_SIZE,
    OTEL_BSP_MAX_QUEUE_SIZE,
    OTEL_BSP_SCHEDULE_DELAY,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult

from microsoft.opentelemetry.a365.core.exporters.enriching_span_processor import (
    _EnrichingBatchSpanProcessor,
    get_span_enricher,
    logger as _processor_logger,
    register_span_enricher,
    unregister_span_enricher,
)

# Real (not simulated) fork-safety coverage needs the multiprocessing "fork"
# start method, which only exists on POSIX. Resolve this once, defensively,
# so a start method already configured by another plugin/module never turns
# into an import-time crash -- it just disables the POSIX-only tests below.
_FORK_AVAILABLE = hasattr(os, "fork")
if _FORK_AVAILABLE:
    try:
        if multiprocessing.get_start_method(allow_none=True) is None:
            multiprocessing.set_start_method("fork")
        _FORK_AVAILABLE = multiprocessing.get_start_method(allow_none=True) == "fork"
    except RuntimeError:
        _FORK_AVAILABLE = False


def _make_span(name: str = "test-span", attributes=None) -> ReadableSpan:
    """Build a MagicMock standing in for a sampled, already-ended ReadableSpan."""
    span = MagicMock(spec=ReadableSpan)
    span.name = name
    span.attributes = {} if attributes is None else attributes
    span.context = MagicMock()
    span.context.trace_flags.sampled = True
    return span


class _RecordingExporter:
    """Thread-safe fake SpanExporter.

    Records every exported span and every ``shutdown()`` call, and can be
    told to block inside ``export()`` until released. Also keeps an ordered
    event log so lifecycle tests can assert *happens-before* relationships
    (e.g. "export finished before exporter.shutdown() ran") using
    synchronization primitives instead of sleeps.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.exported: List[ReadableSpan] = []
        self.export_calls = 0
        self.shutdown_calls = 0
        self.events: List[str] = []
        self.shutdown_thread_name: str = ""
        self._release_gate = threading.Event()
        self._release_gate.set()  # not blocking by default
        self.export_started = threading.Event()
        self.shutdown_called_event = threading.Event()

    def block(self) -> None:
        """Cause export() calls to block until release() is called."""
        self._release_gate.clear()

    def release(self) -> None:
        self._release_gate.set()

    def export(self, spans):
        self.export_started.set()
        with self._lock:
            self.events.append("export_start")
        self._release_gate.wait(timeout=5)
        with self._lock:
            self.exported.extend(spans)
            self.export_calls += 1
            self.events.append("export_end")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        with self._lock:
            self.shutdown_calls += 1
            self.shutdown_thread_name = threading.current_thread().name
            self.events.append("shutdown_called")
        self.shutdown_called_event.set()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class TestSpanEnricherRegistration(unittest.TestCase):
    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    def test_register_enricher(self):
        def my_enricher(span: ReadableSpan) -> ReadableSpan:
            return span

        register_span_enricher(my_enricher)
        self.assertIs(get_span_enricher(), my_enricher)

    def test_unregister_enricher(self):
        def my_enricher(span: ReadableSpan) -> ReadableSpan:
            return span

        register_span_enricher(my_enricher)
        unregister_span_enricher()
        self.assertIsNone(get_span_enricher())

    def test_double_register_raises(self):
        def enricher1(span: ReadableSpan) -> ReadableSpan:
            return span

        def enricher2(span: ReadableSpan) -> ReadableSpan:
            return span

        register_span_enricher(enricher1)
        with self.assertRaises(RuntimeError):
            register_span_enricher(enricher2)

    def test_no_enricher_by_default(self):
        self.assertIsNone(get_span_enricher())

    def test_unregister_when_none(self):
        unregister_span_enricher()  # should not raise


class TestEnrichingBatchSpanProcessorEnrichment(unittest.TestCase):
    """Behavioral (non-white-box) coverage of enrichment/suppression.

    The processor no longer inherits BatchSpanProcessor, so these tests
    exercise the real on_end -> force_flush -> exporter path instead of
    patching a base-class on_end.
    """

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    @staticmethod
    def _make_processor(exporter, **kwargs):
        return _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=10,
            schedule_delay_millis=5,
            max_export_batch_size=10,
            **kwargs,
        )

    def test_on_end_calls_enricher(self):
        enriched = _make_span(name="enriched")

        def my_enricher(span):
            return enriched

        register_span_enricher(my_enricher)

        exporter = _RecordingExporter()
        processor = self._make_processor(exporter)
        try:
            processor.on_end(_make_span(name="original"))
            self.assertTrue(processor.force_flush(timeout_millis=5000))
        finally:
            processor.shutdown()

        self.assertEqual(len(exporter.exported), 1)
        self.assertIs(exporter.exported[0], enriched)

    def test_on_end_falls_back_on_enricher_error(self):
        def bad_enricher(span):
            raise ValueError("enricher error")

        register_span_enricher(bad_enricher)

        exporter = _RecordingExporter()
        processor = self._make_processor(exporter)
        original_span = _make_span(name="original")
        try:
            processor.on_end(original_span)
            self.assertTrue(processor.force_flush(timeout_millis=5000))
        finally:
            processor.shutdown()

        self.assertEqual(len(exporter.exported), 1)
        self.assertIs(exporter.exported[0], original_span)

    def test_suppress_invoke_agent_input(self):
        exporter = _RecordingExporter()
        processor = self._make_processor(exporter, suppress_invoke_agent_input=True)
        span = _make_span(
            name="invoke_agent Travel_Assistant",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.input.messages": "[{...}]",
            },
        )
        try:
            processor.on_end(span)
            self.assertTrue(processor.force_flush(timeout_millis=5000))
        finally:
            processor.shutdown()

        self.assertEqual(len(exporter.exported), 1)
        self.assertNotIn("gen_ai.input.messages", dict(exporter.exported[0].attributes))

    def test_no_suppress_for_non_invoke_agent(self):
        exporter = _RecordingExporter()
        processor = self._make_processor(exporter, suppress_invoke_agent_input=True)
        span = _make_span(
            name="chat gpt-4",
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.input.messages": "[{...}]",
            },
        )
        try:
            processor.on_end(span)
            self.assertTrue(processor.force_flush(timeout_millis=5000))
        finally:
            processor.shutdown()

        self.assertEqual(len(exporter.exported), 1)
        self.assertIs(exporter.exported[0], span)


class TestEnrichingBatchSpanProcessorCapacity(unittest.TestCase):
    """Atomic enqueue/capacity under a producer race (Task 5, Step 1)."""

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    def test_on_end_capacity_race_never_silently_evicts(self):
        """More producer threads than queue capacity race on_end via a barrier.

        Every accepted span must eventually be exported exactly once and
        every rejected span must be explicitly counted -- none may vanish
        silently (e.g. via deque-maxlen eviction of an already-accepted
        span).

        Reaching max_export_batch_size (== max_queue_size here) may
        legitimately wake the worker mid-race (Task 5 hardening finding #1):
        it can pop exactly one batch and then block inside the still-blocked
        exporter, reopening capacity for a bounded number of additional
        acceptances. So the accepted count is asserted as a deterministic
        range instead of a single fixed value -- the pre-fix version of this
        test assumed the worker could never wake here, which the threshold
        wake now correctly contradicts.
        """
        exporter = _RecordingExporter()
        exporter.block()  # the exporter stays blocked: at most one pop-and-block cycle can occur
        max_queue_size = 4
        num_threads = 12
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=max_queue_size,
            # Long enough that the worker only ever wakes via the
            # max_export_batch_size threshold below, never via this timer.
            schedule_delay_millis=60_000,
            max_export_batch_size=max_queue_size,
        )
        try:
            barrier = threading.Barrier(num_threads)
            spans = [_make_span(name=f"span-{i}") for i in range(num_threads)]

            def submit(span):
                barrier.wait(timeout=5)
                processor.on_end(span)

            threads = [threading.Thread(target=submit, args=(spans[i],)) for i in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
                self.assertFalse(t.is_alive())

            # Conservation: every span was either accepted or explicitly
            # counted as dropped -- none vanished silently.
            self.assertEqual(processor._enqueued_total + processor._dropped_count, num_threads)

            # The exporter is still blocked, so at most one threshold-wake
            # batch (<= max_export_batch_size) could have been popped and
            # gone in-flight, reopening capacity exactly once. This bounds
            # the accepted count without depending on exact scheduling.
            self.assertGreaterEqual(processor._enqueued_total, max_queue_size)
            self.assertLessEqual(processor._enqueued_total, max_queue_size + processor._max_export_batch_size)

            exporter.release()
        finally:
            processor.shutdown()

        # Every accepted span -- whether it was still queued or already
        # popped into the in-flight batch at the moment of the assertions
        # above -- was exported exactly once by the time shutdown() finishes
        # draining. This is the core "no silent eviction" guarantee.
        self.assertEqual(len(exporter.exported), processor._enqueued_total)
        self.assertEqual(len(exporter.exported) + processor._dropped_count, num_threads)
        exported_ids: Set[int] = {id(span) for span in exporter.exported}
        self.assertEqual(len(exported_ids), len(exporter.exported), "a span was exported more than once")
        submitted_ids = {id(span) for span in spans}
        self.assertTrue(exported_ids.issubset(submitted_ids))

    def test_on_end_rejects_explicitly_once_queue_is_at_capacity(self):
        """Deterministic (single-threaded) companion to the race test above:
        proves a full queue causes an explicit rejection of the new span
        rather than silently evicting an already-accepted one.

        Bypasses on_end()/_enqueue() for the setup phase, appending directly
        to processor._queue under processor._condition without ever calling
        notify_all(): the worker is never signalled, so (with a schedule
        delay far longer than this test's runtime) it is guaranteed to
        remain parked in its own wait() throughout, and cannot interfere.
        """
        exporter = _RecordingExporter()
        max_queue_size = 4
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=max_queue_size,
            schedule_delay_millis=60_000,
            max_export_batch_size=max_queue_size,
        )
        try:
            accepted_spans = [_make_span(name=f"pre-{i}") for i in range(max_queue_size)]
            with processor._condition:
                processor._queue.extend(accepted_spans)
                processor._enqueued_total = len(accepted_spans)

            overflow_span = _make_span(name="overflow")
            accepted = processor._enqueue(overflow_span)

            self.assertFalse(accepted)
            self.assertEqual(processor._dropped_count, 1)
            self.assertEqual(list(processor._queue), accepted_spans)
            self.assertNotIn(overflow_span, processor._queue)
        finally:
            processor.shutdown()

        self.assertEqual(len(exporter.exported), max_queue_size)
        self.assertEqual({id(s) for s in exporter.exported}, {id(s) for s in accepted_spans})


class TestEnrichingBatchSpanProcessorLifecycle(unittest.TestCase):
    """Deterministic lifecycle ordering tests (Task 5, Step 2)."""

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    def test_shutdown_drains_every_accepted_span(self):
        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=100,
            schedule_delay_millis=60_000,
            max_export_batch_size=5,
        )
        spans = [_make_span(name=f"span-{i}") for i in range(37)]
        for span in spans:
            processor.on_end(span)

        processor.shutdown()

        self.assertEqual(len(exporter.exported), len(spans))
        self.assertEqual({id(s) for s in exporter.exported}, {id(s) for s in spans})
        self.assertEqual(exporter.shutdown_calls, 1)
        self.assertEqual(processor._dropped_count, 0)

    def test_shutdown_waits_for_active_export_before_exporter_shutdown(self):
        exporter = _RecordingExporter()
        exporter.block()  # hold the export open so we can observe it in flight
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=10,
            schedule_delay_millis=60_000,
            max_export_batch_size=10,
        )
        processor.on_end(_make_span())

        shutdown_thread = threading.Thread(target=processor.shutdown)
        shutdown_thread.start()

        # Deterministically wait for export to actually begin -- no sleeps.
        self.assertTrue(exporter.export_started.wait(timeout=5))
        # The export is still blocked: exporter.shutdown must not have run.
        self.assertEqual(exporter.shutdown_calls, 0)

        exporter.release()
        shutdown_thread.join(timeout=5)
        self.assertFalse(shutdown_thread.is_alive())

        self.assertEqual(exporter.shutdown_calls, 1)
        self.assertEqual(exporter.events, ["export_start", "export_end", "shutdown_called"])
        self.assertEqual(exporter.shutdown_thread_name, processor._worker_thread.name)

    def test_shutdown_timeout_leaves_worker_owning_cleanup(self):
        exporter = _RecordingExporter()
        exporter.block()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=10,
            schedule_delay_millis=60_000,
            max_export_batch_size=10,
        )
        processor.on_end(_make_span())

        # shutdown() must give up after its own short timeout while export is
        # still blocked, without ever touching the exporter itself.
        start = time.monotonic()
        processor.shutdown(timeout_millis=50)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 5)
        self.assertEqual(exporter.shutdown_calls, 0)

        # The worker still owns cleanup: once export unblocks, it alone
        # finishes the drain and performs the single exporter.shutdown() call.
        exporter.release()
        self.assertTrue(exporter.shutdown_called_event.wait(timeout=5))
        self.assertEqual(exporter.shutdown_calls, 1)
        self.assertEqual(exporter.shutdown_thread_name, processor._worker_thread.name)

    def test_concurrent_shutdown_calls_exporter_shutdown_once(self):
        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=10,
            schedule_delay_millis=60_000,
            max_export_batch_size=10,
        )
        num_threads = 8
        barrier = threading.Barrier(num_threads)

        def call_shutdown():
            barrier.wait(timeout=5)
            processor.shutdown()

        threads = [threading.Thread(target=call_shutdown) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(exporter.shutdown_calls, 1)
        self.assertEqual(exporter.shutdown_thread_name, processor._worker_thread.name)

    def test_on_end_racing_shutdown_never_strands_or_throws(self):
        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=200,
            schedule_delay_millis=5,
            max_export_batch_size=8,
        )
        num_producers = 8
        spans_per_producer = 25
        total_submitted = num_producers * spans_per_producer
        errors: List[BaseException] = []
        errors_lock = threading.Lock()
        start_barrier = threading.Barrier(num_producers + 1)

        def produce(index):
            start_barrier.wait(timeout=5)
            try:
                for i in range(spans_per_producer):
                    processor.on_end(_make_span(name=f"p{index}-{i}"))
            except BaseException as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        producers = [threading.Thread(target=produce, args=(i,)) for i in range(num_producers)]
        for t in producers:
            t.start()

        start_barrier.wait(timeout=5)  # release producers and shutdown together
        processor.shutdown()  # races with the in-flight on_end calls above

        for t in producers:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(errors, [])
        # Nothing is stranded: every span is either exported or explicitly
        # dropped -- the totals reconcile exactly.
        self.assertEqual(len(exporter.exported) + processor._dropped_count, total_submitted)
        self.assertEqual(len(processor._queue), 0)
        self.assertEqual(processor._active_exports, 0)


class TestEnrichingBatchSpanProcessorThresholdWake(unittest.TestCase):
    """Task 5 hardening finding #1: wake the worker at max_export_batch_size."""

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    def test_batch_threshold_wakes_worker_before_schedule_delay(self):
        """Reaching max_export_batch_size must drain well before the long
        schedule_delay elapses (mirrors upstream's
        ``test_telemetry_exported_once_batch_size_reached``)."""
        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=15,
            max_export_batch_size=15,
            # Not reached during the test -- a spontaneous drain could only
            # happen here via the threshold wake under test.
            schedule_delay_millis=30_000,
        )
        try:
            before = time.monotonic()
            for i in range(15):
                processor.on_end(_make_span(name=f"span-{i}"))

            deadline = time.monotonic() + 2
            while exporter.export_calls == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            elapsed = time.monotonic() - before

            self.assertEqual(exporter.export_calls, 1)
            self.assertEqual(len(exporter.exported), 15)
            self.assertLess(
                elapsed,
                2,
                "worker did not drain until close to the schedule delay -- threshold wake not firing",
            )
        finally:
            processor.shutdown()

    def test_long_delay_burst_never_drops_when_worker_wakes_each_batch(self):
        """A sustained burst far larger than max_queue_size must complete
        with zero drops when schedule_delay is a full day: only possible if
        on_end()/_enqueue() wakes the worker every time the queue reaches
        max_export_batch_size. Without that wake, the queue fills once and
        stays full (the worker only drains on the schedule-delay timer,
        force_flush, or shutdown), so every span submitted afterward would
        be silently rejected (avoidable drop) -- or the test would have to
        block for the full schedule delay to ever observe a drain
        (avoidable stall)."""
        exporter = _RecordingExporter()
        batch_size = 5
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            # Equal to batch size: capacity only ever holds one batch, so if
            # the worker doesn't proactively drain between bursts, the next
            # burst is guaranteed to be rejected outright.
            max_queue_size=batch_size,
            max_export_batch_size=batch_size,
            # A full day: passing proves it is entirely because of the
            # threshold wake, never because of this timer.
            schedule_delay_millis=24 * 60 * 60 * 1000,
        )
        num_batches = 6
        total_spans = batch_size * num_batches
        try:
            for batch_index in range(num_batches):
                for i in range(batch_size):
                    processor.on_end(_make_span(name=f"b{batch_index}-{i}"))

                # Deterministically wait for *this* batch to drain before
                # submitting the next -- bounds the proof to two seconds
                # per batch instead of the 24-hour schedule delay.
                deadline = time.monotonic() + 2
                while exporter.export_calls <= batch_index and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertEqual(
                    exporter.export_calls,
                    batch_index + 1,
                    f"batch {batch_index} was not drained within 2s -- worker stalled instead of waking",
                )
        finally:
            processor.shutdown()

        self.assertEqual(processor._dropped_count, 0)
        self.assertEqual(len(exporter.exported), total_spans)


class TestEnrichingBatchSpanProcessorEnvDefaults(unittest.TestCase):
    """Task 5 hardening finding #3: OTEL_BSP_* env vars seed the defaults
    when constructor args are None, exactly like upstream BatchSpanProcessor
    (including invalid-value fallback behavior)."""

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    @staticmethod
    def _without_bsp_env_vars():
        return {k: v for k, v in os.environ.items() if not k.startswith("OTEL_BSP_")}

    @mock.patch.dict(
        os.environ,
        {
            OTEL_BSP_MAX_QUEUE_SIZE: "10",
            OTEL_BSP_SCHEDULE_DELAY: "2000",
            OTEL_BSP_MAX_EXPORT_BATCH_SIZE: "3",
            OTEL_BSP_EXPORT_TIMEOUT: "4000",
        },
    )
    def test_env_vars_used_when_args_omitted(self):
        processor = _EnrichingBatchSpanProcessor(_RecordingExporter())
        try:
            self.assertEqual(processor._max_queue_size, 10)
            self.assertEqual(processor._schedule_delay_seconds, 2.0)
            self.assertEqual(processor._max_export_batch_size, 3)
            self.assertEqual(processor._export_timeout_millis, 4000)
        finally:
            processor.shutdown()

    def test_defaults_used_when_no_env_vars_and_no_args(self):
        with mock.patch.dict(os.environ, self._without_bsp_env_vars(), clear=True):
            processor = _EnrichingBatchSpanProcessor(_RecordingExporter())
        try:
            self.assertEqual(processor._max_queue_size, 2048)
            self.assertEqual(processor._schedule_delay_seconds, 5.0)
            self.assertEqual(processor._max_export_batch_size, 512)
            self.assertEqual(processor._export_timeout_millis, 30000)
        finally:
            processor.shutdown()

    @mock.patch.dict(
        os.environ,
        {
            OTEL_BSP_MAX_QUEUE_SIZE: "a",
            OTEL_BSP_SCHEDULE_DELAY: " ",
            OTEL_BSP_MAX_EXPORT_BATCH_SIZE: "One",
            OTEL_BSP_EXPORT_TIMEOUT: "@",
        },
    )
    def test_invalid_env_vars_fall_back_to_defaults(self):
        _processor_logger.disabled = True
        try:
            processor = _EnrichingBatchSpanProcessor(_RecordingExporter())
        finally:
            _processor_logger.disabled = False
        try:
            self.assertEqual(processor._max_queue_size, 2048)
            self.assertEqual(processor._schedule_delay_seconds, 5.0)
            self.assertEqual(processor._max_export_batch_size, 512)
            self.assertEqual(processor._export_timeout_millis, 30000)
        finally:
            processor.shutdown()

    @mock.patch.dict(
        os.environ,
        {OTEL_BSP_MAX_QUEUE_SIZE: "10", OTEL_BSP_MAX_EXPORT_BATCH_SIZE: "10"},
    )
    def test_explicit_args_take_precedence_over_env_vars(self):
        processor = _EnrichingBatchSpanProcessor(_RecordingExporter(), max_queue_size=99, max_export_batch_size=9)
        try:
            self.assertEqual(processor._max_queue_size, 99)
            self.assertEqual(processor._max_export_batch_size, 9)
        finally:
            processor.shutdown()


class _CountingLogHandler(logging.Handler):
    """Non-blocking fake handler that just records every emitted record."""

    def __init__(self):
        super().__init__()
        self.records: List[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


class _BlockingLogHandler(logging.Handler):
    """A log handler whose emit() blocks until release() is called.

    Stands in for a slow or misbehaving log sink (e.g. a network handler).
    """

    def __init__(self):
        super().__init__()
        self.emit_started = threading.Event()
        self._release = threading.Event()

    def release(self):
        self._release.set()

    def emit(self, record):
        self.emit_started.set()
        self._release.wait(timeout=5)


class TestEnrichingBatchSpanProcessorDropLogging(unittest.TestCase):
    """Task 5 hardening finding #4: per-drop/post-shutdown logging must run
    outside the processor's lock and must not turn into a log storm."""

    def setUp(self):
        unregister_span_enricher()
        self._logger = logging.getLogger("microsoft.opentelemetry.a365.core.exporters.enriching_span_processor")
        self._prev_level = self._logger.level
        self._logger.setLevel(logging.DEBUG)

    def tearDown(self):
        self._logger.setLevel(self._prev_level)
        unregister_span_enricher()

    def test_repeated_post_shutdown_drops_are_throttled(self):
        handler = _CountingLogHandler()
        self._logger.addHandler(handler)
        try:
            exporter = _RecordingExporter()
            processor = _EnrichingBatchSpanProcessor(
                exporter,
                max_queue_size=10,
                schedule_delay_millis=60_000,
                max_export_batch_size=10,
            )
            processor.shutdown()  # _accepting is now False: every on_end() below drops deterministically

            for i in range(100):
                processor.on_end(_make_span(name=f"dropped-{i}"))

            info_records = [r for r in handler.records if r.levelno == logging.INFO]
            self.assertEqual(
                len(info_records),
                1,
                "each post-shutdown drop logged independently -- no throttling of a repeated message",
            )
        finally:
            self._logger.removeHandler(handler)

    def test_blocking_log_handler_does_not_hold_processor_lock(self):
        handler = _BlockingLogHandler()
        self._logger.addHandler(handler)
        try:
            exporter = _RecordingExporter()
            processor = _EnrichingBatchSpanProcessor(
                exporter,
                max_queue_size=10,
                schedule_delay_millis=60_000,
                max_export_batch_size=10,
            )
            processor.shutdown()  # deterministic drop path: no capacity/timing races needed

            stuck_thread = threading.Thread(target=processor.on_end, args=(_make_span(),))
            stuck_thread.start()
            try:
                self.assertTrue(handler.emit_started.wait(timeout=5), "log call never reached the handler")

                # The lock must already be free here: proves _enqueue() logs
                # *after* releasing self._condition, so a slow/blocking log
                # handler can never starve the worker or other producers.
                acquired = processor._condition.acquire(timeout=2)
                self.assertTrue(
                    acquired,
                    "processor._condition was held while a log handler was blocked in emit()",
                )
                processor._condition.release()

                # A second, independent producer must not be blocked either.
                second_done = threading.Event()

                def second_call():
                    processor.on_end(_make_span())
                    second_done.set()

                second_thread = threading.Thread(target=second_call)
                second_thread.start()
                self.assertTrue(second_done.wait(timeout=2), "a second producer was blocked by the stuck log call")
                second_thread.join(timeout=2)
            finally:
                handler.release()
                stuck_thread.join(timeout=5)
            self.assertFalse(stuck_thread.is_alive())
        finally:
            self._logger.removeHandler(handler)


class TestEnrichingBatchSpanProcessorForkSafety(unittest.TestCase):
    """Task 5 hardening finding #2: PID-guard fallback path.

    Exercises the enqueue-time PID guard directly, without an actual
    ``os.fork()``, so it runs on every platform including Windows. The old
    (pre-"fork") worker thread here is a harmless leftover daemon thread
    sleeping on a schedule delay far longer than this test's runtime -- in a
    real fork it simply would not exist in the child at all. End-to-end
    ``os.fork()`` coverage lives in ``TestEnrichingBatchSpanProcessorForkPosix``
    below.
    """

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    def test_pid_change_reinitializes_queue_state_and_worker(self):
        exporter = _RecordingExporter()
        exporter.block()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=10,
            schedule_delay_millis=5_000,
            max_export_batch_size=10,
        )
        try:
            stale_span = _make_span(name="pre-fork")
            processor.on_end(stale_span)
            self.assertEqual(len(processor._queue), 1)
            old_worker = processor._worker_thread

            # Simulate "we are now the forked child" -- nothing actually
            # forked, but a stale pid is exactly what a real os.fork()
            # child observes on its very next enqueue.
            processor._pid = -1

            fresh_span = _make_span(name="post-fork")
            processor.on_end(fresh_span)

            # State was reinitialized: the stale pre-"fork" span is gone,
            # only the fresh one is queued, and a brand-new worker thread is
            # running under the current pid.
            self.assertEqual(len(processor._queue), 1)
            self.assertIs(processor._queue[0], fresh_span)
            self.assertIsNot(processor._worker_thread, old_worker)
            self.assertTrue(processor._worker_thread.is_alive())
            self.assertEqual(processor._pid, os.getpid())
            self.assertEqual(processor._dropped_count, 0)
        finally:
            exporter.release()
            processor.shutdown()

        self.assertEqual(exporter.exported, [fresh_span])

    def test_register_at_fork_hook_uses_a_weakref(self):
        """The at-fork registration must not keep the processor alive
        forever via a strong reference in the process-wide fork registry."""
        if not hasattr(os, "register_at_fork"):
            self.skipTest("os.register_at_fork not available on this platform")

        import gc
        import weakref

        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(exporter, max_queue_size=10, max_export_batch_size=10)
        processor.shutdown()
        weak_processor = weakref.ref(processor)

        del processor
        gc.collect()

        self.assertIsNone(weak_processor(), "processor was kept alive by the os.register_at_fork hook")


@unittest.skipUnless(_FORK_AVAILABLE, "requires POSIX fork with the 'fork' multiprocessing start method")
class TestEnrichingBatchSpanProcessorForkPosix(unittest.TestCase):
    """Task 5 hardening finding #2: real os.fork() end-to-end coverage.

    POSIX-only: os.fork()/os.register_at_fork() do not exist on Windows, so
    this whole class is skipped there.
    """

    def setUp(self):
        unregister_span_enricher()

    def tearDown(self):
        unregister_span_enricher()

    def test_fork_child_reinitializes_and_exports_independently(self):
        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=200,
            max_export_batch_size=10,
            schedule_delay_millis=30_000,
        )
        try:
            # Queued in the parent only. A real child process has no
            # visibility into it -- the worker thread that would have
            # drained it does not survive the fork.
            for i in range(9):
                processor.on_end(_make_span(name=f"parent-{i}"))

            def child(conn):
                try:
                    for i in range(100):
                        processor.on_end(_make_span(name=f"child-{i}"))
                    flushed = processor.force_flush(timeout_millis=5000)
                    # Assert full delivery, not an exact batch count: the
                    # worker (a genuinely concurrent OS thread in the child)
                    # may interleave partial drains with this tight
                    # enqueue loop, so the number of individual export()
                    # calls it takes to move all 100 spans is not
                    # deterministic -- only the total delivered count is.
                    conn.send(flushed and len(exporter.exported) == 100)
                finally:
                    conn.close()

            parent_conn, child_conn = multiprocessing.Pipe()
            process = multiprocessing.Process(target=child, args=(child_conn,))
            process.start()
            try:
                self.assertTrue(parent_conn.poll(10), "child process did not report back in time")
                self.assertTrue(parent_conn.recv(), "child did not export all 100 of its own spans")
            finally:
                process.join(10)
            self.assertEqual(process.exitcode, 0)
            self.assertFalse(process.is_alive())
        finally:
            processor.force_flush(timeout_millis=5000)
            processor.shutdown()

        # Only the parent's own pre-fork spans were ever exported here: the
        # child's copy-on-write memory keeps its 100 spans/exports entirely
        # invisible to the parent's exporter instance.
        self.assertEqual(exporter.export_calls, 1)
        self.assertEqual(len(exporter.exported), 9)

    def test_fork_child_shutdown_and_force_flush_do_not_hang(self):
        exporter = _RecordingExporter()
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=50,
            max_export_batch_size=10,
            schedule_delay_millis=30_000,
        )
        try:
            processor.on_end(_make_span(name="pre-fork"))

            def child(conn):
                try:
                    for i in range(5):
                        processor.on_end(_make_span(name=f"child-{i}"))
                    flushed = processor.force_flush(timeout_millis=5000)
                    processor.shutdown(timeout_millis=5000)
                    conn.send(bool(flushed))
                finally:
                    conn.close()

            parent_conn, child_conn = multiprocessing.Pipe()
            process = multiprocessing.Process(target=child, args=(child_conn,))
            process.start()
            try:
                # Bounded wait: a hang here (an inherited, stuck lock) would
                # be exactly the fork-safety regression under test.
                self.assertTrue(parent_conn.poll(10), "child's force_flush/shutdown hung after fork")
                self.assertTrue(parent_conn.recv())
            finally:
                process.join(10)
            self.assertEqual(process.exitcode, 0)
            self.assertFalse(process.is_alive())
        finally:
            processor.shutdown()


if __name__ == "__main__":
    unittest.main()
