# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Span enrichment support for the Agent365 exporter pipeline.

Provides a span processor that runs registered enrichers against each span
before it is exported, allowing additional attributes to be attached without
mutating the original span.
"""

from __future__ import annotations

import collections
import logging
import os
import threading
import time
import weakref
from collections.abc import Callable
from typing import Deque, Dict, List, Optional

from opentelemetry.context import _SUPPRESS_INSTRUMENTATION_KEY, Context, attach, detach, set_value
from opentelemetry.sdk.environment_variables import (
    OTEL_BSP_EXPORT_TIMEOUT,
    OTEL_BSP_MAX_EXPORT_BATCH_SIZE,
    OTEL_BSP_MAX_QUEUE_SIZE,
    OTEL_BSP_SCHEDULE_DELAY,
)
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter

from microsoft.opentelemetry.a365.constants import (
    GEN_AI_INPUT_MESSAGES_KEY,
    GEN_AI_OPERATION_NAME_KEY,
    INVOKE_AGENT_OPERATION_NAME,
)
from microsoft.opentelemetry.a365.core.exporters.enriched_span import EnrichedReadableSpan

logger = logging.getLogger(__name__)

# Mirrors opentelemetry.sdk.trace.export.BatchSpanProcessor's own defaults so
# behavior is unchanged for callers that omit these options.
_DEFAULT_MAX_QUEUE_SIZE = 2048
_DEFAULT_SCHEDULE_DELAY_MILLIS = 5000
_DEFAULT_MAX_EXPORT_BATCH_SIZE = 512
_DEFAULT_EXPORT_TIMEOUT_MILLIS = 30000
_DEFAULT_SHUTDOWN_TIMEOUT_MILLIS = 30000

# How long a repeated drop reason (queue full / shutting down) stays
# suppressed after being logged once, so a sustained drop condition cannot
# turn into a log storm.
_DROP_LOG_INTERVAL_SECONDS = 10.0

_ENV_VAR_INT_VALUE_ERROR_MESSAGE = "Unable to parse value for %s as an integer; using default of %s."


def _int_env_default(env_var: str, default: int) -> int:
    """Resolve an integer option from an environment variable, falling back
    to ``default`` both when the variable is unset and when it holds a
    value that cannot be parsed as an integer -- mirroring
    BatchSpanProcessor's own ``_default_*()`` helpers (arg wins over env
    var, env var wins over the hardcoded default, invalid values are
    logged and never raise).
    """
    try:
        return int(os.environ.get(env_var, default))
    except ValueError:
        logger.exception(_ENV_VAR_INT_VALUE_ERROR_MESSAGE, env_var, default)
        return default


# Single span enricher - only one platform instrumentor should be active at a time
_span_enricher: Optional[Callable[[ReadableSpan], ReadableSpan]] = None
_enricher_lock = threading.Lock()


# pylint: disable=global-statement, broad-exception-caught
def register_span_enricher(enricher: Callable[[ReadableSpan], ReadableSpan]) -> None:
    """Register the span enricher for the active platform instrumentor.

    Only one enricher can be registered at a time since auto-instrumentation
    is platform-specific (Semantic Kernel, LangChain, or OpenAI Agents).

    Raises RuntimeError if an enricher is already registered.
    """
    global _span_enricher  # noqa: PLW0603
    with _enricher_lock:
        if _span_enricher is not None:
            raise RuntimeError(
                "A span enricher is already registered. Only one platform instrumentor can be active at a time."
            )
        _span_enricher = enricher
        logger.debug("Span enricher registered: %s", enricher.__name__)


def unregister_span_enricher() -> None:
    """Unregister the current span enricher."""
    global _span_enricher  # noqa: PLW0603
    with _enricher_lock:
        if _span_enricher is not None:
            logger.debug("Span enricher unregistered: %s", _span_enricher.__name__)
            _span_enricher = None


def get_span_enricher() -> Optional[Callable[[ReadableSpan], ReadableSpan]]:
    """Get the currently registered span enricher."""
    with _enricher_lock:
        return _span_enricher


def _validate_batch_options(max_queue_size: int, schedule_delay_millis: float, max_export_batch_size: int) -> None:
    """Validate batching options, mirroring BatchSpanProcessor's own guard rails."""
    if max_queue_size <= 0:
        raise ValueError("max_queue_size must be a positive integer.")
    if schedule_delay_millis <= 0:
        raise ValueError("schedule_delay_millis must be positive.")
    if max_export_batch_size <= 0:
        raise ValueError("max_export_batch_size must be a positive integer.")
    if max_export_batch_size > max_queue_size:
        raise ValueError("max_export_batch_size must be less than or equal to max_queue_size.")


def _resolve_batch_options(
    max_queue_size: Optional[int] = None,
    schedule_delay_millis: Optional[float] = None,
    max_export_batch_size: Optional[int] = None,
    export_timeout_millis: Optional[float] = None,
) -> tuple[int, float, int, float]:
    """Resolve effective batch options and validate their combined values."""
    resolved_max_queue_size = (
        max_queue_size
        if max_queue_size is not None
        else _int_env_default(OTEL_BSP_MAX_QUEUE_SIZE, _DEFAULT_MAX_QUEUE_SIZE)
    )
    resolved_schedule_delay_millis = (
        schedule_delay_millis
        if schedule_delay_millis is not None
        else _int_env_default(OTEL_BSP_SCHEDULE_DELAY, _DEFAULT_SCHEDULE_DELAY_MILLIS)
    )
    resolved_max_export_batch_size = (
        max_export_batch_size
        if max_export_batch_size is not None
        else _int_env_default(OTEL_BSP_MAX_EXPORT_BATCH_SIZE, _DEFAULT_MAX_EXPORT_BATCH_SIZE)
    )
    resolved_export_timeout_millis = (
        export_timeout_millis
        if export_timeout_millis is not None
        else _int_env_default(OTEL_BSP_EXPORT_TIMEOUT, _DEFAULT_EXPORT_TIMEOUT_MILLIS)
    )
    _validate_batch_options(
        resolved_max_queue_size,
        resolved_schedule_delay_millis,
        resolved_max_export_batch_size,
    )
    return (
        resolved_max_queue_size,
        resolved_schedule_delay_millis,
        resolved_max_export_batch_size,
        resolved_export_timeout_millis,
    )


class _EnrichingBatchSpanProcessor(SpanProcessor):
    """SpanProcessor that enriches spans, then atomically batches and exports them.

    This owns a dedicated worker thread backed by a bounded ``deque`` and a
    single ``Condition``. Capacity is reserved and the span is enqueued
    atomically under that lock, so producers racing on a full queue are
    explicitly rejected rather than silently evicting an already-accepted
    span. Enqueuing a span that brings the queue to ``max_export_batch_size``
    wakes the worker immediately instead of waiting for the schedule delay,
    matching upstream's threshold-wake behavior. ``shutdown()`` stops new
    acceptance, wakes the worker, and waits; only the worker thread drains
    the remaining queue, waits out any in-flight export, and performs the
    single ``exporter.shutdown()`` call. Concurrent ``shutdown()`` callers
    all wait on that same completion signal, so exporter shutdown always
    happens exactly once.

    Fork safety mirrors upstream's BatchSpanProcessor: an ``os.register_at_fork``
    hook (held via a weakref so it never keeps this processor alive) and a
    PID guard checked on every enqueue both reinitialize the condition,
    queue, and worker thread after a fork, since only the calling thread
    survives ``os.fork()`` and the old worker/lock state would otherwise be
    silently abandoned or, worse, deadlocked in the child.
    """

    def __init__(
        self,
        span_exporter: SpanExporter,
        max_queue_size: Optional[int] = None,
        schedule_delay_millis: Optional[float] = None,
        max_export_batch_size: Optional[int] = None,
        export_timeout_millis: Optional[float] = None,
        *,
        suppress_invoke_agent_input: bool = False,
    ) -> None:
        self._exporter = span_exporter
        self._suppress_invoke_agent_input = suppress_invoke_agent_input

        (
            max_queue_size,
            schedule_delay_millis,
            max_export_batch_size,
            export_timeout_millis,
        ) = _resolve_batch_options(
            max_queue_size=max_queue_size,
            schedule_delay_millis=schedule_delay_millis,
            max_export_batch_size=max_export_batch_size,
            export_timeout_millis=export_timeout_millis,
        )

        self._max_queue_size = max_queue_size
        self._schedule_delay_seconds = schedule_delay_millis / 1000.0
        self._max_export_batch_size = max_export_batch_size
        # Retained for interface/configuration parity with BatchSpanProcessor;
        # there is no way to pass a per-call timeout through to
        # SpanExporter.export() today.
        self._export_timeout_millis = export_timeout_millis

        # Guards the PID-guard fallback in _check_fork_reinit() so a fork
        # racing concurrently with an in-flight enqueue reinitializes state
        # exactly once. Deliberately not recreated in _at_fork_reinit(): it
        # protects the reinit itself, not the state being reinitialized.
        self._fork_reinit_lock = threading.Lock()

        self._init_state_after_fork()

        self._pid = os.getpid()
        if hasattr(os, "register_at_fork"):
            # A bound-method strong reference here would be kept alive
            # forever by the process-wide fork registry (there is no
            # unregister API), leaking this processor. A weakref lets the
            # hook become a no-op once nothing else references us.
            weak_at_fork_reinit = weakref.WeakMethod(self._at_fork_reinit)

            def _after_fork_in_child() -> None:
                reinit = weak_at_fork_reinit()
                if reinit is not None:
                    reinit()

            os.register_at_fork(after_in_child=_after_fork_in_child)

    def _init_state_after_fork(self) -> None:
        """(Re)initialize all per-process mutable state and start a fresh
        worker thread. Used both by __init__ and by _at_fork_reinit()."""
        # Single lock/condition guards all mutable state below. The worker
        # releases it only while an export (or the final exporter.shutdown())
        # call is actually in flight.
        self._condition = threading.Condition()
        self._queue: Deque[ReadableSpan] = collections.deque()
        self._active_exports = 0
        self._accepting = True
        self._shutdown_requested = False
        self._shutdown_complete = False
        self._wake_requested = False
        self._enqueued_total = 0
        self._completed_total = 0
        self._dropped_count = 0

        # Guards the per-reason drop-log throttle state below. Deliberately
        # separate from self._condition so a slow/blocking log handler can
        # never be reached while the main condition is held, and so a
        # throttle check can never itself be blocked by another thread's
        # in-flight (slow) logging call.
        self._drop_log_lock = threading.Lock()
        self._last_drop_log_time: Dict[str, float] = {}
        self._suppressed_drop_count: Dict[str, int] = {}

        self._worker_thread = threading.Thread(
            name="A365EnrichingBatchSpanProcessor",
            target=self._worker,
            daemon=True,
        )
        self._worker_thread.start()

    def _check_fork_reinit(self) -> None:
        """Defense-in-depth PID guard for enqueue, covering platforms or
        call paths where the os.register_at_fork hook above did not fire.
        Mirrors BatchProcessor.emit()'s own pid check."""
        if self._pid == os.getpid():
            return
        with self._fork_reinit_lock:
            if self._pid == os.getpid():
                return
            self._at_fork_reinit()

    def _at_fork_reinit(self) -> None:
        """Recreate all per-process state after os.fork(). Only the calling
        thread survives a fork: the old worker thread, and any lock/condition
        state it held, are simply gone in the child -- reusing them could
        hang forever rather than merely losing already-queued spans."""
        self._init_state_after_fork()
        self._pid = os.getpid()

    # Backward-compat accessor mirroring BatchSpanProcessor.span_exporter.
    @property
    def span_exporter(self) -> SpanExporter:
        return self._exporter

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        """No-op: this processor only acts on span end."""

    def on_end(self, span: ReadableSpan) -> None:
        """Apply enrichment/suppression, then atomically enqueue for export."""
        enriched_span = span

        enricher = get_span_enricher()
        if enricher is not None:
            try:
                enriched_span = enricher(span)
            except Exception:
                logger.exception(
                    "Span enricher %s raised an exception, using original span",
                    enricher.__name__,
                )

        # Apply input message suppression for InvokeAgent spans
        if self._suppress_invoke_agent_input:
            attrs = enriched_span.attributes or {}
            operation_name = attrs.get(GEN_AI_OPERATION_NAME_KEY)
            if (
                enriched_span.name.startswith(INVOKE_AGENT_OPERATION_NAME)
                and operation_name == INVOKE_AGENT_OPERATION_NAME
            ):
                enriched_span = EnrichedReadableSpan(
                    enriched_span,
                    extra_attributes={},
                    excluded_attribute_keys={GEN_AI_INPUT_MESSAGES_KEY},
                )

        if not (enriched_span.context and enriched_span.context.trace_flags.sampled):
            return

        self._enqueue(enriched_span)

    def _enqueue(self, span: ReadableSpan) -> bool:
        """Reserve capacity and enqueue atomically. Returns whether accepted."""
        self._check_fork_reinit()

        drop_reason: Optional[str] = None
        accepted = False
        with self._condition:
            if not self._accepting:
                self._dropped_count += 1
                drop_reason = "shutdown"
            elif len(self._queue) >= self._max_queue_size:
                self._dropped_count += 1
                drop_reason = "queue_full"
            else:
                self._queue.append(span)
                self._enqueued_total += 1
                accepted = True
                if len(self._queue) >= self._max_export_batch_size:
                    # Wake the worker now instead of waiting for the
                    # schedule delay to elapse -- otherwise a queue that
                    # fills to capacity between schedule-delay ticks would
                    # stall (or, once truly full, start dropping) even
                    # though the worker could have drained it immediately.
                    self._wake_requested = True
                    self._condition.notify_all()

        # Logging never happens while self._condition is held: a slow or
        # blocking handler (or a log storm from a sustained drop condition)
        # must never be able to stall the worker or other producer threads.
        if drop_reason is not None:
            self._log_dropped_span(drop_reason)
        return accepted

    def _log_dropped_span(self, reason: str) -> None:
        """Log a dropped-span message, throttled per reason so a sustained
        drop condition (queue full, or draining after shutdown) logs at
        most once every _DROP_LOG_INTERVAL_SECONDS instead of once per
        dropped span."""
        now = time.monotonic()
        with self._drop_log_lock:
            last = self._last_drop_log_time.get(reason)
            if last is not None and (now - last) < _DROP_LOG_INTERVAL_SECONDS:
                self._suppressed_drop_count[reason] = self._suppressed_drop_count.get(reason, 0) + 1
                return
            suppressed = self._suppressed_drop_count.pop(reason, 0)
            self._last_drop_log_time[reason] = now

        if reason == "shutdown":
            message = "A365 span processor is shutting down; dropping span."
            level = logging.INFO
        else:
            message = "A365 span queue is full (max_queue_size=%d); dropping span." % self._max_queue_size
            level = logging.WARNING
        if suppressed:
            message += (
                f" ({suppressed} further drops of this kind suppressed"
                f" in the last {_DROP_LOG_INTERVAL_SECONDS:.0f}s)"
            )
        logger.log(level, message)

    def _worker(self) -> None:
        """Own the queue: batch, export outside the lock, then drain-to-exit on shutdown."""
        with self._condition:
            while True:
                if not self._wake_requested:
                    self._condition.wait(timeout=self._schedule_delay_seconds)
                self._wake_requested = False
                self._drain_locked()
                if self._shutdown_requested and not self._queue and self._active_exports == 0:
                    break
            self._finalize_locked()

    def _drain_locked(self) -> None:
        """Export batches of up to max_export_batch_size until the queue is empty.

        Caller holds ``self._condition``; it is released only around the
        actual (blocking) export call.
        """
        while self._queue:
            batch: List[ReadableSpan] = [
                self._queue.popleft() for _ in range(min(len(self._queue), self._max_export_batch_size))
            ]
            self._active_exports += 1
            self._condition.release()
            try:
                self._export_batch(batch)
            finally:
                self._condition.acquire()
                self._active_exports -= 1
                self._completed_total += len(batch)
                # Wake any force_flush()/shutdown() callers waiting on progress.
                self._condition.notify_all()

    def _export_batch(self, batch: List[ReadableSpan]) -> None:
        token = attach(set_value(_SUPPRESS_INSTRUMENTATION_KEY, True))
        try:
            self._exporter.export(batch)
        except Exception:
            logger.exception("Exception while exporting spans from the A365 batch processor.")
        finally:
            detach(token)

    def _finalize_locked(self) -> None:
        """Perform the single exporter.shutdown() call. Caller holds the condition on entry."""
        self._condition.release()
        try:
            self._exporter.shutdown()
        except Exception:
            logger.exception("Exception while shutting down the A365 span exporter.")
        finally:
            self._condition.acquire()
            self._shutdown_complete = True
            self._condition.notify_all()

    def shutdown(self, timeout_millis: Optional[int] = None) -> None:
        """Stop accepting new spans, drain the queue, then shut down the exporter once.

        Safe to call concurrently from multiple threads: every caller waits
        on the same completion signal, and only the worker thread ever calls
        ``exporter.shutdown()``. If ``timeout_millis`` elapses first, this
        call returns without touching the exporter; the worker keeps running
        in the background and remains the sole owner of that cleanup.
        """
        if timeout_millis is None:
            timeout_millis = _DEFAULT_SHUTDOWN_TIMEOUT_MILLIS
        deadline = time.monotonic() + (timeout_millis / 1000.0)
        with self._condition:
            self._accepting = False
            self._shutdown_requested = True
            self._wake_requested = True
            self._condition.notify_all()
            while not self._shutdown_complete:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._condition.wait(timeout=remaining)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Block until every span enqueued so far has been exported (or attempted)."""
        deadline = time.monotonic() + (timeout_millis / 1000.0)
        with self._condition:
            if not self._accepting:
                # Shutdown already started/finished; it owns draining now.
                return False
            target = self._enqueued_total
            self._wake_requested = True
            self._condition.notify_all()
            while self._completed_total < target:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
        return True
