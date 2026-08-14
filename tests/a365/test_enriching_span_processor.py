# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import threading
import time
import unittest
from typing import List, Set
from unittest.mock import MagicMock

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult

from microsoft.opentelemetry.a365.core.exporters.enriching_span_processor import (
    _EnrichingBatchSpanProcessor,
    get_span_enricher,
    register_span_enricher,
    unregister_span_enricher,
)


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

        Every accepted span must eventually be exported and every rejected
        span must be explicitly counted -- none may vanish silently (e.g. via
        deque-maxlen eviction of an already-accepted span).
        """
        exporter = _RecordingExporter()
        exporter.block()  # belt-and-suspenders: a spurious drain would hang, not lie
        max_queue_size = 4
        num_threads = 12
        processor = _EnrichingBatchSpanProcessor(
            exporter,
            max_queue_size=max_queue_size,
            # Large enough that the worker cannot wake spontaneously during
            # the race window -- capacity accounting must hold with zero
            # help from timing.
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

            # The worker never woke, so the queue holds exactly what fit and
            # nothing was drained mid-race.
            self.assertEqual(len(processor._queue), max_queue_size)
            self.assertEqual(processor._dropped_count, num_threads - max_queue_size)

            queued_ids: Set[int] = {id(span) for span in processor._queue}
            self.assertEqual(len(queued_ids), max_queue_size)

            exporter.release()
        finally:
            processor.shutdown()

        # Every accepted span was exported exactly once; totals reconcile.
        self.assertEqual(len(exporter.exported), max_queue_size)
        self.assertEqual(len(exporter.exported) + processor._dropped_count, num_threads)
        exported_ids = {id(span) for span in exporter.exported}
        self.assertEqual(exported_ids, queued_ids)


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


if __name__ == "__main__":
    unittest.main()
