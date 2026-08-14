# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Agent365 span exporter.

Exports OpenTelemetry spans to the Agent365 observability ingestion endpoint,
handling authentication, batching, and payload size limits.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Optional, final
from urllib.parse import urlparse

import requests
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from microsoft.opentelemetry._sdkstats import is_sdkstats_enabled
from microsoft.opentelemetry.a365.core.exporters.durable_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    IdentityKey,
    TransmissionGate,
)
from microsoft.opentelemetry.a365.core.exporters.persistent_storage import (
    DurableRecord,
    PersistentStorage,
)
from microsoft.opentelemetry.a365.core.exporters.replay_coordinator import (
    ReplayCoordinator,
    ReplayEndpointError,
    ReplayIdentityError,
)
from microsoft.opentelemetry.a365.core.exporters.token_resolver_context import (
    AgentIdentity,
    TokenResolverContext,
)
from microsoft.opentelemetry.a365.core.exporters.utils import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    build_export_url,
    chunk_by_size,
    estimate_span_bytes,
    get_validated_domain_override,
    hex_span_id,
    hex_trace_id,
    kind_name,
    parse_retry_after,
    filter_and_partition_by_identity,
    status_name,
    truncate_span,
)
from microsoft.opentelemetry.a365.constants import A365_HTTP_TIMEOUT_SECONDS, GEN_AI_AGENT_AUID_KEY

# mypy: disable-error-code="import-untyped, union-attr"

# Hardcoded constants - not configurable
DEFAULT_HTTP_TIMEOUT_SECONDS = A365_HTTP_TIMEOUT_SECONDS
DEFAULT_ENDPOINT_URL = "https://agent365.svc.cloud.microsoft"

_403_DOCS_URL = "https://aka.ms/a365-403"
_403_FOUNDRY_URL = "https://aka.ms/foundry-grant-agent-365-permissions"

logger = logging.getLogger(__name__)


@final
# pylint: disable=broad-exception-caught
class _Agent365Exporter(SpanExporter):
    """Agent365 span exporter.

    * Partitions spans by (tenantId, agentId)
    * Builds OTLP-like JSON: resourceSpans -> scopeSpans -> spans
    * POSTs per group to the Agent365 observability endpoint
    * Adds Bearer token via contextual_token_resolver(context) when set,
      otherwise falls back to token_resolver(agentId, tenantId)
    """

    def __init__(
        self,
        token_resolver: Optional[Callable[[str, str], str | None]] = None,
        contextual_token_resolver: Optional[Callable[[TokenResolverContext], str | None]] = None,
        cluster_category: str = "prod",
        use_s2s_endpoint: bool = False,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        storage_directory: Optional[Path] = None,
        enable_durable_delivery: bool = True,
    ):
        if token_resolver is None and contextual_token_resolver is None:
            raise ValueError("token_resolver or contextual_token_resolver must be provided.")
        if max_payload_bytes <= 0:
            raise ValueError(f"max_payload_bytes must be positive, got {max_payload_bytes}")
        self._session = requests.Session()
        self._closed = False
        self._lock = threading.Lock()
        # Set once the single shutdown owner finishes closing storage/session.
        # Concurrent shutdown() callers wait on this instead of returning
        # early, so every caller sees resources closed before it returns.
        self._shutdown_complete = threading.Event()
        self._token_resolver = token_resolver
        self._contextual_token_resolver = contextual_token_resolver
        self._cluster_category = cluster_category
        self._use_s2s_endpoint = use_s2s_endpoint
        self._max_payload_bytes = max_payload_bytes
        self._domain_override = get_validated_domain_override()
        self.record_sdkstats = is_sdkstats_enabled()

        # Durable delivery: a per-identity gate throttles retries, a persistent
        # queue holds undelivered payloads, and a replay coordinator drains the
        # queue on a background daemon thread. Storage and the coordinator are
        # created lazily on first export so merely constructing an exporter does
        # not touch the filesystem or spawn a thread.
        self._gate = TransmissionGate()
        self._enable_durable_delivery = enable_durable_delivery
        self._storage_directory = storage_directory
        self._storage: Optional[PersistentStorage] = None
        self._replay: Optional[ReplayCoordinator] = None
        self._replay_started = False

    # ------------- Durable delivery lifecycle -------------

    def _ensure_durable_initialized(self) -> None:
        """Create the durable queue and replay coordinator once, on demand."""
        if not self._enable_durable_delivery:
            return
        with self._lock:
            if self._closed or self._storage is not None:
                return
            try:
                storage = PersistentStorage(directory=self._storage_directory)
            except Exception as e:
                logger.error(
                    "Durable delivery disabled: failed to initialize persistent storage: %s", e
                )
                self._enable_durable_delivery = False
                return
            self._storage = storage
            self._replay = ReplayCoordinator(storage, self._gate, self._replay_record)

    def _ensure_replay_started(self) -> None:
        """Start the replay thread once so it drains any queued payloads."""
        replay = self._replay
        if replay is None:
            return
        with self._lock:
            if self._replay_started or self._closed:
                return
            self._replay_started = True
        replay.start()

    # ------------- SpanExporter API -----------------

    def _resolve_token(self, agent_id: str, tenant_id: str, activities: list[ReadableSpan]) -> Optional[str]:
        """Resolve auth token, preferring contextual_token_resolver when set."""
        if self._contextual_token_resolver is not None:
            agentic_user_id: Optional[str] = None
            if activities:
                first_attrs = activities[0].attributes or {}
                raw_auid = first_attrs.get(GEN_AI_AGENT_AUID_KEY)
                if raw_auid is not None:
                    agentic_user_id = str(raw_auid)
            identity = AgentIdentity(agent_id, agentic_user_id)
            context = TokenResolverContext(identity, tenant_id)
            return self._contextual_token_resolver(context)
        # Constructor guarantees at least one resolver is set.
        assert self._token_resolver is not None
        return self._token_resolver(agent_id, tenant_id)

    def _resolve_token_for_replay(self, record: DurableRecord) -> Optional[str]:
        """Resolve an auth token for a queued record using its stored identity."""
        if self._contextual_token_resolver is not None:
            identity = AgentIdentity(record.agent_id, record.agentic_user_id)
            context = TokenResolverContext(identity, record.tenant_id)
            return self._contextual_token_resolver(context)
        assert self._token_resolver is not None
        return self._token_resolver(record.agent_id, record.tenant_id)

    def _identity_key(
        self, tenant_id: str, agent_id: str, activities: Sequence[ReadableSpan]
    ) -> IdentityKey:
        """Build the durable-delivery identity for a partitioned span group."""
        agentic_user_id: Optional[str] = None
        if activities:
            first_attrs = activities[0].attributes or {}
            raw_auid = first_attrs.get(GEN_AI_AGENT_AUID_KEY)
            if raw_auid is not None:
                agentic_user_id = str(raw_auid)
        return IdentityKey(tenant_id, agent_id, agentic_user_id, self._use_s2s_endpoint)

    def _build_export_url(self, tenant_id: str, agent_id: str, use_s2s_endpoint: bool) -> str:
        endpoint = self._domain_override or DEFAULT_ENDPOINT_URL
        return build_export_url(endpoint, agent_id, tenant_id, use_s2s_endpoint)

    @staticmethod
    def _ensure_https_replay_url(url: str) -> None:
        if urlparse(url).scheme.lower() != "https":
            raise ReplayEndpointError(
                f"Replay endpoint must use HTTPS before resolving a bearer token: {url}"
            )

    def export(  # pylint: disable=too-many-statements
        self, spans: Sequence[ReadableSpan]
    ) -> SpanExportResult:
        if self._closed:
            return SpanExportResult.FAILURE

        self._ensure_durable_initialized()
        self._ensure_replay_started()

        try:
            groups = filter_and_partition_by_identity(spans)
            if not groups:
                # No eligible genAI spans to export after filtering/partitioning; treat as success
                logger.info("No eligible genAI spans to export; nothing exported.")
                return SpanExportResult.SUCCESS

            total_spans = sum(len(activities) for activities in groups.values())
            logger.debug(
                "Found %d identity groups with %d total spans to export",
                len(groups),
                total_spans,
            )

            all_delivered_or_stored = True
            persisted_any = False

            for (tenant_id, agent_id), activities in groups.items():
                identity = self._identity_key(tenant_id, agent_id, activities)

                # Map and truncate spans first, then chunk by estimated byte size
                mapped_spans = self._map_and_truncate_spans(activities)
                resource_attrs = self._get_resource_attributes(activities)
                chunks = chunk_by_size(
                    mapped_spans,
                    lambda ms: estimate_span_bytes(ms[0]),
                    self._max_payload_bytes,
                )

                if len(chunks) > 1:
                    logger.debug(
                        "Split %d spans into %d chunks for tenantId: %s, agentId: %s",
                        len(activities),
                        len(chunks),
                        tenant_id,
                        agent_id,
                    )

                url = self._build_export_url(tenant_id, agent_id, self._use_s2s_endpoint)

                logger.debug(
                    "Exporting %d spans to endpoint: %s (tenant: %s, agent: %s)",
                    len(activities),
                    url,
                    tenant_id,
                    agent_id,
                )

                # Resolve auth once per identity group.
                token: Optional[str] = None
                token_resolution_failed = False
                try:
                    token = self._resolve_token(agent_id, tenant_id, activities)
                except Exception as e:
                    logger.error(
                        "Token resolution failed for agent %s, tenant %s: %s",
                        agent_id,
                        tenant_id,
                        e,
                    )
                    token_resolution_failed = True

                for i, chunk in enumerate(chunks):
                    body = self._serialize_chunk(chunk, resource_attrs, i, len(chunks), tenant_id, agent_id)

                    # Token resolver raised: persist so a later replay can retry
                    # once credentials recover. A successful store counts as success.
                    if token_resolution_failed:
                        if self._persist(identity, body):
                            persisted_any = True
                        else:
                            all_delivered_or_stored = False
                        continue

                    # Empty token is a permanent condition: never send, never store.
                    if not token:
                        logger.error(
                            "No token resolved for agent %s, tenant %s; dropping chunk %d of %d.",
                            agent_id,
                            tenant_id,
                            i + 1,
                            len(chunks),
                        )
                        all_delivered_or_stored = False
                        continue

                    if not url.lower().startswith("https://"):
                        logger.warning(
                            "The authorization token is being sent over a non-HTTPS connection. "
                            "This may expose credentials in transit."
                        )
                    headers: dict[str, str | bytes] = {
                        "content-type": "application/json",
                        "authorization": f"Bearer {token}",
                    }

                    # The gate rejects sends for an identity in a retry cooldown;
                    # persist directly rather than hammering the endpoint.
                    if not self._gate.try_acquire(identity):
                        if self._persist(identity, body):
                            persisted_any = True
                        else:
                            all_delivered_or_stored = False
                        continue

                    try:
                        result = self._post_once(url, body, headers)
                    except Exception as post_exc:  # pylint: disable=broad-except
                        # _post_once classifies transport errors internally, so
                        # reaching here means an unexpected failure. Release the
                        # half-open probe we just acquired so the identity is not
                        # permanently gated, then persist the payload for replay.
                        logger.error(
                            "Unexpected error sending telemetry for tenant %s, agent %s: %s",
                            tenant_id,
                            agent_id,
                            post_exc,
                        )
                        self._gate.release_probe(identity)
                        if self._persist(identity, body):
                            persisted_any = True
                        else:
                            all_delivered_or_stored = False
                        continue

                    if result.disposition is DeliveryDisposition.DELIVERED:
                        self._gate.record_success(identity)
                    elif result.disposition is DeliveryDisposition.RETRYABLE:
                        self._gate.record_retryable_failure(identity, result.retry_after)
                        if self._persist(identity, body):
                            persisted_any = True
                        else:
                            all_delivered_or_stored = False
                    else:
                        # Permanent: the endpoint answered definitively. The
                        # identity itself is healthy, so reset the gate; only this
                        # payload is undeliverable and is dropped.
                        self._gate.record_success(identity)
                        all_delivered_or_stored = False
                        break

            if persisted_any and self._replay is not None:
                self._replay.wake()

            return SpanExportResult.SUCCESS if all_delivered_or_stored else SpanExportResult.FAILURE

        except Exception as e:
            logger.error("Export failed with exception: %s", e)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Stop durable delivery and close storage/session exactly once.

        The first caller becomes the single cleanup owner: it signals the
        replay coordinator to stop and -- critically -- waits (unbounded)
        until the replay thread has actually exited before closing storage
        or the HTTP session, so an in-flight replay send can never observe a
        closed resource. Concurrent callers (including a caller that arrives
        after ownership was already claimed) wait on the same completion
        event instead of returning early, so every ``shutdown()`` call only
        returns once cleanup has actually finished.
        """
        with self._lock:
            if self._closed:
                owner = False
            else:
                self._closed = True
                owner = True
                replay = self._replay
                storage = self._storage

        if not owner:
            self._shutdown_complete.wait()
            return

        # Everything below runs outside self._lock, both so a concurrent
        # export() cannot deadlock against the joining replay thread and so
        # the (possibly long) replay join is never done while holding a lock
        # other callers need merely to observe self._closed.
        if replay is not None:
            try:
                if not replay.shutdown(None):
                    # Only reachable if shutdown() were somehow invoked from
                    # the replay thread itself; a thread can never join
                    # itself. Log it -- this indicates a reentrant call, not
                    # a timeout -- and fall through to close resources since
                    # there is no safe way to wait further here.
                    logger.warning(
                        "A365 replay coordinator could not be joined from its own thread "
                        "during shutdown(); proceeding to close durable storage."
                    )
            except Exception as e:
                logger.error("Error shutting down replay coordinator: %s", e)
        if storage is not None:
            try:
                storage.close()
            except Exception as e:
                logger.error("Error closing durable storage: %s", e)
        try:
            self._session.close()
        except Exception:
            pass
        self._shutdown_complete.set()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    # ------------- HTTP helper ----------------------

    @staticmethod
    def _truncate_text(text: str, max_length: int) -> str:
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    @staticmethod
    def _extract_token_identity(headers: dict[str, str | bytes]) -> dict[str, str]:
        """Decode the Bearer JWT and return service principal claims as a dict.

        Returns a dict with 'app_id' and/or 'object_id' keys, or an empty dict
        if the token is absent or cannot be decoded.
        """
        try:
            auth = headers.get("authorization", "")
            if isinstance(auth, bytes):
                auth = auth.decode("utf-8", errors="replace")
            if not auth.startswith("Bearer "):
                return {}
            parts = auth[len("Bearer ") :].split(".")
            if len(parts) != 3:
                return {}
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            sp: dict[str, str] = {}
            if payload.get("appid") or payload.get("azp"):
                sp["app_id"] = payload.get("appid") or payload.get("azp")
            if payload.get("oid"):
                sp["object_id"] = payload["oid"]
            return sp
        except Exception:  # pylint: disable=broad-except
            return {}

    def _serialize_chunk(
        self,
        chunk: Sequence[tuple[dict[str, Any], str, str | None]],
        resource_attrs: dict[str, Any],
        index: int,
        total: int,
        tenant_id: str,
        agent_id: str,
    ) -> str:
        """Build the JSON request body for one chunk and warn on size drift."""
        payload = self._build_envelope(chunk, resource_attrs)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        body_bytes = len(body.encode("utf-8"))
        logger.debug(
            "Prepared chunk %d of %d (%d spans, %d bytes)",
            index + 1,
            total,
            len(chunk),
            body_bytes,
        )
        # Defensive check: the estimator covers per-span content but not envelope
        # overhead (resource attributes, scope wrappers). Warn if the assembled
        # body exceeds the configured limit so operators can observe estimator
        # drift before the server starts rejecting requests.
        if body_bytes > self._max_payload_bytes:
            logger.warning(
                "Chunk %d of %d body size (%d bytes) exceeds max_payload_bytes (%d); "
                "estimator may be under-counting envelope overhead. "
                "Tenant: %s, agent: %s, spans: %d.",
                index + 1,
                total,
                body_bytes,
                self._max_payload_bytes,
                tenant_id,
                agent_id,
                len(chunk),
            )
        return body

    def _persist(self, identity: IdentityKey, body: str) -> bool:
        """Persist one payload to the durable queue. Returns False on failure."""
        storage = self._storage
        if storage is None:
            logger.warning(
                "Durable storage unavailable; telemetry for tenant %s, agent %s could not be "
                "persisted and will be dropped.",
                identity.tenant_id,
                identity.agent_id,
            )
            return False
        stored = storage.store(DurableRecord.new(identity, body))
        if not stored:
            logger.error(
                "Durable storage rejected telemetry for tenant %s, agent %s.",
                identity.tenant_id,
                identity.agent_id,
            )
        return stored

    def _replay_record(self, record: DurableRecord) -> DeliveryResult:
        """Replay a queued record, rebuilding auth from its stored identity.

        A token-resolution failure (exception or empty token) is surfaced as
        :class:`ReplayIdentityError` so the coordinator releases the record for a
        future attempt instead of dropping it.
        """
        url = self._build_export_url(
            record.tenant_id,
            record.agent_id,
            record.use_s2s_endpoint,
        )
        self._ensure_https_replay_url(url)
        try:
            token = self._resolve_token_for_replay(record)
        except Exception as e:
            raise ReplayIdentityError(
                f"Token resolution failed during replay for agent {record.agent_id}, "
                f"tenant {record.tenant_id}: {e}"
            ) from e
        if not token:
            raise ReplayIdentityError(
                f"No token resolved during replay for agent {record.agent_id}, "
                f"tenant {record.tenant_id}."
            )
        headers: dict[str, str | bytes] = {
            "content-type": "application/json",
            "authorization": "Bearer " + token,
        }
        return self._post_once(url, record.payload, headers)

    def _post_once(  # pylint: disable=too-many-statements,too-many-branches
        self, url: str, body: str, headers: dict[str, str | bytes]
    ) -> DeliveryResult:
        """Perform a single classified HTTP send. No retries, no sleeping.

        Returns a :class:`DeliveryResult`:

        * ``DELIVERED`` for 2xx responses.
        * ``RETRYABLE`` for 401/408/429, all 5xx, and transport-level errors
          (``requests.RequestException``, which includes connect/read timeouts).
        * ``PERMANENT`` for 403 and all other 4xx responses.

        Any ``Retry-After`` header is parsed and returned on the result but is
        never slept on; the transmission gate applies the delay asynchronously.
        """
        # Local imports to avoid pulling sdkstats into the exporter module's
        # import graph for consumers that don't use this package.
        from urllib.parse import urlparse
        from microsoft.opentelemetry._sdkstats._constants import ENDPOINT_A365
        from microsoft.opentelemetry._sdkstats._utils import (
            THROTTLE_STATUS_CODES,
            record_duration,
            record_exception,
            record_failure,
            record_retry,
            record_success,
            record_throttle,
        )

        host = urlparse(url).hostname or url
        record_a365_sdkstats = self.record_sdkstats
        start_time = time.time()
        try:
            resp = self._session.post(
                url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )

            correlation_id = resp.headers.get("x-ms-correlation-id") or resp.headers.get("request-id") or "N/A"
            status_code = resp.status_code

            if 200 <= status_code < 300:
                if record_a365_sdkstats:
                    record_success(ENDPOINT_A365, host)
                logger.debug(
                    "HTTP %d success. Correlation ID: %s. Response: %s",
                    status_code,
                    correlation_id,
                    self._truncate_text(resp.text, 200),
                )
                return DeliveryResult(DeliveryDisposition.DELIVERED)

            response_text = self._truncate_text(resp.text, 500)
            retry_after = parse_retry_after(resp.headers)

            # Retryable: transient auth (401), request timeout (408), throttling
            # (429), and all 5xx server errors.
            if status_code in (401, 408, 429) or 500 <= status_code < 600:
                if record_a365_sdkstats:
                    if status_code in THROTTLE_STATUS_CODES:
                        record_throttle(ENDPOINT_A365, host, status_code)
                    else:
                        record_retry(ENDPOINT_A365, host, status_code)
                logger.warning(
                    "HTTP %d retryable error; payload will be queued for durable retry. "
                    "Correlation ID: %s. Response: %s. Retry-After: %s.",
                    status_code,
                    correlation_id,
                    response_text,
                    retry_after if retry_after is not None else "N/A",
                )
                return DeliveryResult(DeliveryDisposition.RETRYABLE, retry_after)

            # Permanent: 403 and all other 4xx responses.
            if record_a365_sdkstats:
                if status_code in THROTTLE_STATUS_CODES:
                    record_throttle(ENDPOINT_A365, host, status_code)
                else:
                    record_failure(ENDPOINT_A365, host, status_code)
            www_auth = resp.headers.get("www-authenticate", "")
            if status_code == 403 and "insufficient_scope" in www_auth:
                sp = self._extract_token_identity(headers)
                if sp:
                    sp_parts = [
                        f"{label}: {sp[key]}"
                        for key, label in (("app_id", "app ID"), ("object_id", "object ID"))
                        if sp.get(key)
                    ]
                    sp_str = f" service principal ({', '.join(sp_parts)})"
                else:
                    sp_str = " your application's service principal"
                logger.error(
                    "HTTP 403 authorization error: the token is missing the required "
                    "'Agent365.Observability.OtelWrite' app role. "
                    "Grant the 'Agent365.Observability.OtelWrite' role to%s "
                    "and ensure admin consent has been granted. "
                    "| Setup instructions: %s "
                    "| For Foundry: %s "
                    "| Correlation ID: %s.",
                    sp_str,
                    _403_DOCS_URL,
                    _403_FOUNDRY_URL,
                    correlation_id,
                )
            else:
                logger.error(
                    "HTTP %d non-retryable error. Correlation ID: %s. Response: %s. "
                    "WWW-Authenticate: %s. Response headers: %s",
                    status_code,
                    correlation_id,
                    response_text,
                    www_auth or "N/A",
                    dict(resp.headers),
                )
            return DeliveryResult(DeliveryDisposition.PERMANENT)

        except requests.RequestException as e:
            if record_a365_sdkstats:
                record_exception(ENDPOINT_A365, host, type(e).__name__)
            logger.error("Request to %s failed: %s", url, e)
            return DeliveryResult(DeliveryDisposition.RETRYABLE)
        finally:
            if record_a365_sdkstats:
                record_duration(ENDPOINT_A365, host, time.time() - start_time)

    # ------------- Payload mapping ------------------

    def _map_and_truncate_spans(self, spans: Sequence[ReadableSpan]) -> list[tuple[dict[str, Any], str, str | None]]:
        """Map ReadableSpans to OTLP dicts and apply per-span truncation.

        Returns a list of (mapped_span, scope_name, scope_version) tuples so
        that envelope grouping by instrumentation scope can be performed
        efficiently after byte-size chunking.
        """
        result: list[tuple[dict[str, Any], str, str | None]] = []
        for sp in spans:
            scope = sp.instrumentation_scope
            scope_name = scope.name if scope is not None else "unknown"
            scope_version = scope.version if scope is not None else None
            result.append((self._map_span(sp), scope_name, scope_version))
        return result

    @staticmethod
    def _get_resource_attributes(spans: Sequence[ReadableSpan]) -> dict[str, Any]:
        """Extract resource attributes from the first span in the batch."""
        if spans:
            return dict(getattr(spans[0].resource, "attributes", {}) or {})
        return {}

    def _build_envelope(
        self,
        mapped_spans: Sequence[tuple[dict[str, Any], str, str | None]],
        resource_attrs: dict[str, Any],
    ) -> dict[str, Any]:
        """Build an OTLP export request envelope from pre-mapped spans."""
        scope_map: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        for mapped_span, scope_name, scope_version in mapped_spans:
            scope_map.setdefault((scope_name, scope_version), []).append(mapped_span)

        scope_spans: list[dict[str, Any]] = [
            {
                "scope": {"name": name, "version": version},
                "spans": spans,
            }
            for (name, version), spans in scope_map.items()
        ]

        return {
            "resourceSpans": [
                {
                    "resource": {"attributes": resource_attrs or None},
                    "scopeSpans": scope_spans,
                }
            ]
        }

    def _map_span(self, sp: ReadableSpan) -> dict[str, Any]:
        ctx = sp.get_span_context()

        parent_span_id = None
        if sp.parent is not None and sp.parent.span_id != 0:
            parent_span_id = hex_span_id(sp.parent.span_id)

        attrs = dict(sp.attributes or {})

        events: list[dict[str, Any]] | None = None
        if sp.events:
            events = []
            for ev in sp.events:
                ev_attrs = dict(ev.attributes or {}) if ev.attributes else None
                events.append(
                    {
                        "timeUnixNano": ev.timestamp,
                        "name": ev.name,
                        "attributes": ev_attrs,
                    }
                )

        links: list[dict[str, Any]] | None = None
        if sp.links:
            links = []
            for ln in sp.links:
                ln_attrs = dict(ln.attributes or {}) if ln.attributes else None
                links.append(
                    {
                        "traceId": hex_trace_id(ln.context.trace_id),
                        "spanId": hex_span_id(ln.context.span_id),
                        "attributes": ln_attrs,
                    }
                )

        status_code = sp.status.status_code if sp.status else StatusCode.UNSET
        status = {
            "code": status_name(status_code),
            "message": getattr(sp.status, "description", "") or "",
        }

        span_dict: dict[str, Any] = {
            "traceId": hex_trace_id(ctx.trace_id),
            "spanId": hex_span_id(ctx.span_id),
            "parentSpanId": parent_span_id,
            "name": sp.name,
            "kind": kind_name(sp.kind),
            "startTimeUnixNano": sp.start_time,
            "endTimeUnixNano": sp.end_time,
            "attributes": attrs or None,
            "events": events,
            "links": links,
            "status": status,
        }

        return truncate_span(span_dict)
