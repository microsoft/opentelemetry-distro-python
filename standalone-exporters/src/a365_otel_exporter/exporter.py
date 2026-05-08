"""A365 OpenTelemetry SpanExporter implementation."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import requests
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from a365_otel_exporter.auth import TokenResolver
from a365_otel_exporter.baggage import (
    ATTR_AGENT_ID,
    ATTR_TENANT_ID,
    BAGGAGE_AGENT_ID,
    BAGGAGE_TENANT_ID,
)

logger = logging.getLogger(__name__)

# Mapping from opentelemetry.trace.SpanKind to OTLP integer values.
_SPAN_KIND_MAP: Dict[SpanKind, int] = {
    SpanKind.INTERNAL: 1,
    SpanKind.SERVER: 2,
    SpanKind.CLIENT: 3,
    SpanKind.PRODUCER: 4,
    SpanKind.CONSUMER: 5,
}

# Mapping from opentelemetry.trace.StatusCode to OTLP integer values.
_STATUS_CODE_MAP: Dict[StatusCode, int] = {
    StatusCode.UNSET: 0,
    StatusCode.OK: 1,
    StatusCode.ERROR: 2,
}

_DEFAULT_ENDPOINT = "https://agent365.svc.cloud.microsoft"
_DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class A365ExporterOptions:
    """Configuration for :class:`A365SpanExporter`.

    Parameters
    ----------
    token_resolver:
        A synchronous callable ``(agent_id, tenant_id) -> bearer_token``.
        Return ``None`` to skip the batch (the exporter will log a warning).
    endpoint:
        Base URL of the A365 observability service.
    timeout_seconds:
        HTTP POST timeout in seconds.
    """

    token_resolver: TokenResolver
    endpoint: str = _DEFAULT_ENDPOINT
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS


class A365SpanExporter(SpanExporter):
    """Export OpenTelemetry spans to Agent 365 Observability.

    This exporter groups spans by ``(tenant_id, agent_id)`` and sends each
    group as an OTLP JSON payload to the A365 trace ingestion endpoint.

    Routing attributes are read from span attributes with the following
    lookup order:

    1. ``a365.tenant_id`` / ``a365.agent_id``  (set via
       :func:`~a365_otel_exporter.baggage.set_a365_span_attributes`)
    2. ``tenant_id`` / ``agent_id``  (set via OTel Baggage propagation)

    Spans that do not carry both values are silently skipped (a DEBUG log
    message is emitted).
    """

    def __init__(self, options: A365ExporterOptions) -> None:
        if options.token_resolver is None:
            raise ValueError("token_resolver is required in A365ExporterOptions")
        self._token_resolver = options.token_resolver
        self._endpoint = options.endpoint.rstrip("/")
        self._timeout = options.timeout_seconds
        self._session = requests.Session()
        self._shutdown = False

    # ------------------------------------------------------------------
    # SpanExporter interface
    # ------------------------------------------------------------------

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a batch of spans to A365.

        Spans are grouped by ``(tenant_id, agent_id)``.  Each group is sent
        as a separate HTTP POST in OTLP JSON format.  If any group fails the
        entire batch is reported as ``FAILURE``.
        """
        if self._shutdown:
            logger.warning("export() called after shutdown")
            return SpanExportResult.FAILURE

        groups = self._group_spans(spans)
        if not groups:
            logger.debug("No spans with A365 routing attributes; nothing to export")
            return SpanExportResult.SUCCESS

        all_ok = True
        for (tenant_id, agent_id), group_spans in groups.items():
            try:
                ok = self._export_group(tenant_id, agent_id, group_spans)
                if not ok:
                    all_ok = False
            except Exception:
                logger.error(
                    "Unexpected error exporting spans for tenant_id=%s agent_id=%s",
                    tenant_id,
                    agent_id,
                    exc_info=True,
                )
                all_ok = False

        return SpanExportResult.SUCCESS if all_ok else SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Shut down the exporter and release resources."""
        self._shutdown = True
        self._session.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush is a no-op -- spans are exported synchronously."""
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _group_spans(
        self, spans: Sequence[ReadableSpan]
    ) -> Dict[Tuple[str, str], List[ReadableSpan]]:
        """Group spans by (tenant_id, agent_id).

        Spans missing either attribute are skipped with a DEBUG log message.
        """
        groups: Dict[Tuple[str, str], List[ReadableSpan]] = defaultdict(list)
        skipped = 0

        for span in spans:
            tenant_id = self._read_routing_attr(span, ATTR_TENANT_ID, BAGGAGE_TENANT_ID)
            agent_id = self._read_routing_attr(span, ATTR_AGENT_ID, BAGGAGE_AGENT_ID)

            if tenant_id is None or agent_id is None:
                skipped += 1
                continue

            groups[(tenant_id, agent_id)].append(span)

        if skipped > 0:
            logger.debug(
                "Skipped %d span(s) missing tenant_id or agent_id attributes",
                skipped,
            )

        return dict(groups)

    @staticmethod
    def _read_routing_attr(
        span: ReadableSpan, primary_key: str, fallback_key: str
    ) -> Optional[str]:
        """Read a routing attribute from the span, trying primary then fallback."""
        attrs = span.attributes or {}
        value = attrs.get(primary_key)
        if value is not None:
            return str(value)
        value = attrs.get(fallback_key)
        if value is not None:
            return str(value)
        return None

    def _export_group(
        self,
        tenant_id: str,
        agent_id: str,
        spans: List[ReadableSpan],
    ) -> bool:
        """Export a single (tenant_id, agent_id) group of spans."""
        token = self._token_resolver(agent_id, tenant_id)
        if token is None:
            logger.warning(
                "Token resolver returned None for agent_id=%s tenant_id=%s; "
                "skipping %d span(s)",
                agent_id,
                tenant_id,
                len(spans),
            )
            return False

        url = (
            f"{self._endpoint}/observabilityService/tenants/{tenant_id}"
            f"/otlp/agents/{agent_id}/traces"
        )
        body = self._build_otlp_json(spans)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            resp = self._session.post(
                url, data=json.dumps(body), headers=headers, timeout=self._timeout
            )
            if resp.status_code < 200 or resp.status_code >= 300:
                logger.warning(
                    "A365 ingestion returned HTTP %d for tenant_id=%s agent_id=%s: %s",
                    resp.status_code,
                    tenant_id,
                    agent_id,
                    resp.text[:500],
                )
                return False
            logger.debug(
                "Exported %d span(s) for tenant_id=%s agent_id=%s",
                len(spans),
                tenant_id,
                agent_id,
            )
            return True
        except requests.RequestException:
            logger.error(
                "HTTP error exporting spans for tenant_id=%s agent_id=%s",
                tenant_id,
                agent_id,
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # OTLP JSON serialization
    # ------------------------------------------------------------------

    def _build_otlp_json(self, spans: List[ReadableSpan]) -> dict:
        """Build an OTLP ``ExportTraceServiceRequest`` JSON structure."""
        # Group spans by (resource, instrumentation_scope) for proper nesting.
        resource_map: Dict[int, dict] = {}
        scope_map: Dict[Tuple[int, Tuple[str, str]], List[dict]] = defaultdict(list)

        for span in spans:
            resource = span.resource
            res_id = id(resource)
            if res_id not in resource_map:
                resource_map[res_id] = self._resource_to_otlp(resource)

            scope = span.instrumentation_info
            scope_name = getattr(scope, "name", "") or ""
            scope_version = getattr(scope, "version", "") or ""
            scope_key = (res_id, (scope_name, scope_version))

            scope_map[scope_key].append(self._span_to_otlp(span))

        # Assemble resourceSpans -> scopeSpans -> spans.
        resource_spans_by_id: Dict[int, dict] = {}
        for (res_id, (s_name, s_version)), otlp_spans in scope_map.items():
            if res_id not in resource_spans_by_id:
                resource_spans_by_id[res_id] = {
                    "resource": resource_map[res_id],
                    "scopeSpans": [],
                }
            resource_spans_by_id[res_id]["scopeSpans"].append(
                {
                    "scope": {"name": s_name, "version": s_version},
                    "spans": otlp_spans,
                }
            )

        return {"resourceSpans": list(resource_spans_by_id.values())}

    @staticmethod
    def _resource_to_otlp(resource) -> dict:
        """Convert a Resource to OTLP JSON."""
        attrs = {}
        if resource and resource.attributes:
            attrs = _attributes_to_otlp(dict(resource.attributes))
        return {"attributes": attrs}

    @staticmethod
    def _span_to_otlp(span: ReadableSpan) -> dict:
        """Convert a ReadableSpan to OTLP JSON span representation."""
        ctx = span.context
        trace_id = format(ctx.trace_id, "032x") if ctx else ""
        span_id = format(ctx.span_id, "016x") if ctx else ""

        parent_span_id = ""
        if span.parent is not None:
            parent_id = getattr(span.parent, "span_id", None)
            if parent_id is not None:
                parent_span_id = format(parent_id, "016x")

        kind = _SPAN_KIND_MAP.get(span.kind, 1)

        start_ns = str(span.start_time) if span.start_time is not None else "0"
        end_ns = str(span.end_time) if span.end_time is not None else "0"

        attributes = _attributes_to_otlp(dict(span.attributes)) if span.attributes else {}

        status = {"code": 0, "message": ""}
        if span.status is not None:
            status = {
                "code": _STATUS_CODE_MAP.get(span.status.status_code, 0),
                "message": span.status.description or "",
            }

        events = []
        if span.events:
            for event in span.events:
                events.append(
                    {
                        "name": event.name,
                        "timeUnixNano": str(event.timestamp) if event.timestamp else "0",
                        "attributes": _attributes_to_otlp(
                            dict(event.attributes)
                        )
                        if event.attributes
                        else {},
                    }
                )

        links = []
        if span.links:
            for link in span.links:
                link_ctx = link.context
                links.append(
                    {
                        "traceId": format(link_ctx.trace_id, "032x") if link_ctx else "",
                        "spanId": format(link_ctx.span_id, "016x") if link_ctx else "",
                        "attributes": _attributes_to_otlp(
                            dict(link.attributes)
                        )
                        if link.attributes
                        else {},
                    }
                )

        return {
            "traceId": trace_id,
            "spanId": span_id,
            "parentSpanId": parent_span_id,
            "name": span.name,
            "kind": kind,
            "startTimeUnixNano": start_ns,
            "endTimeUnixNano": end_ns,
            "attributes": attributes,
            "status": status,
            "events": events,
            "links": links,
        }


def _attributes_to_otlp(attrs: Dict) -> list:
    """Convert a dict of attributes to OTLP key-value list format.

    OTLP expects attributes as::

        [{"key": "k", "value": {"stringValue": "v"}}, ...]

    Supported value types: str, bool, int, float, bytes, and sequences
    of those types.
    """
    result = []
    for key, value in attrs.items():
        otlp_value = _convert_value(value)
        if otlp_value is not None:
            result.append({"key": str(key), "value": otlp_value})
    return result


def _convert_value(value) -> Optional[dict]:
    """Convert a single attribute value to its OTLP typed representation."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, bytes):
        return {"bytesValue": value.hex()}
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            converted = _convert_value(item)
            if converted is not None:
                items.append(converted)
        return {"arrayValue": {"values": items}}
    # Fallback: convert to string.
    logger.debug("Converting unsupported attribute type %s to string", type(value).__name__)
    return {"stringValue": str(value)}
