# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from unittest.mock import MagicMock

from opentelemetry.trace import SpanKind, StatusCode

from microsoft.opentelemetry.a365.core.exporters.utils import (
    MAX_SPAN_SIZE_BYTES,
    _as_str,
    build_export_url,
    get_validated_domain_override,
    hex_span_id,
    hex_trace_id,
    is_agent365_exporter_enabled,
    kind_name,
    parse_retry_after,
    filter_and_partition_by_identity,
    status_name,
    truncate_span,
)


class TestHexConversions(unittest.TestCase):
    def test_hex_trace_id_zero(self):
        self.assertEqual(hex_trace_id(0), "0" * 32)

    def test_hex_trace_id_nonzero(self):
        result = hex_trace_id(0xABCDEF1234567890ABCDEF1234567890)
        self.assertEqual(result, "abcdef1234567890abcdef1234567890")

    def test_hex_span_id_zero(self):
        self.assertEqual(hex_span_id(0), "0" * 16)

    def test_hex_span_id_nonzero(self):
        result = hex_span_id(0xABCDEF1234567890)
        self.assertEqual(result, "abcdef1234567890")


class TestAsStr(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(_as_str(None))

    def test_empty(self):
        self.assertIsNone(_as_str(""))

    def test_whitespace(self):
        self.assertIsNone(_as_str("   "))

    def test_string(self):
        self.assertEqual(_as_str("hello"), "hello")

    def test_int(self):
        self.assertEqual(_as_str(42), "42")


class TestKindName(unittest.TestCase):
    def test_internal(self):
        self.assertEqual(kind_name(SpanKind.INTERNAL), "INTERNAL")

    def test_client(self):
        self.assertEqual(kind_name(SpanKind.CLIENT), "CLIENT")

    def test_server(self):
        self.assertEqual(kind_name(SpanKind.SERVER), "SERVER")


class TestStatusName(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(status_name(StatusCode.OK), "OK")

    def test_error(self):
        self.assertEqual(status_name(StatusCode.ERROR), "ERROR")

    def test_unset(self):
        self.assertEqual(status_name(StatusCode.UNSET), "UNSET")


class TestTruncateSpan(unittest.TestCase):
    def test_small_span_unchanged(self):
        span = {"name": "test", "attributes": {"key": "value"}}
        result = truncate_span(span)
        self.assertEqual(result, span)

    def test_large_span_truncated(self):
        large_value = "x" * (MAX_SPAN_SIZE_BYTES + 1000)
        span = {"name": "test", "attributes": {"big": large_value, "small": "ok"}}
        result = truncate_span(span)
        self.assertEqual(result["attributes"]["big"], "TRUNCATED")
        self.assertEqual(result["attributes"]["small"], "ok")

    def test_original_not_mutated(self):
        large_value = "x" * (MAX_SPAN_SIZE_BYTES + 1000)
        span = {"name": "test", "attributes": {"big": large_value}}
        truncate_span(span)
        self.assertEqual(span["attributes"]["big"], large_value)  # type: ignore[index]

    def test_empty_attributes(self):
        span = {"name": "test", "attributes": {}}
        result = truncate_span(span)
        self.assertEqual(result, span)

    def test_no_attributes(self):
        span = {"name": "test"}
        result = truncate_span(span)
        self.assertEqual(result, span)


class TestFilterAndPartitionByIdentity(unittest.TestCase):
    def _make_span(self, tenant_id, agent_id, operation_name="invoke_agent"):
        span = MagicMock()
        attrs = {
            "microsoft.tenant.id": tenant_id,
            "gen_ai.agent.id": agent_id,
        }
        if operation_name is not None:
            attrs["gen_ai.operation.name"] = operation_name
        span.attributes = attrs
        return span

    def test_groups_by_identity(self):
        s1 = self._make_span("t1", "a1")
        s2 = self._make_span("t1", "a1")
        s3 = self._make_span("t2", "a2")
        result = filter_and_partition_by_identity([s1, s2, s3])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[("t1", "a1")]), 2)
        self.assertEqual(len(result[("t2", "a2")]), 1)

    def test_skips_missing_tenant(self):
        span = MagicMock()
        span.attributes = {"gen_ai.agent.id": "a1", "gen_ai.operation.name": "invoke_agent"}
        result = filter_and_partition_by_identity([span])
        self.assertEqual(len(result), 0)

    def test_skips_missing_agent(self):
        span = MagicMock()
        span.attributes = {"microsoft.tenant.id": "t1", "gen_ai.operation.name": "invoke_agent"}
        result = filter_and_partition_by_identity([span])
        self.assertEqual(len(result), 0)

    def test_skips_empty_values(self):
        span = MagicMock()
        span.attributes = {
            "microsoft.tenant.id": "",
            "gen_ai.agent.id": "a1",
            "gen_ai.operation.name": "invoke_agent",
        }
        result = filter_and_partition_by_identity([span])
        self.assertEqual(len(result), 0)

    def test_empty_spans(self):
        result = filter_and_partition_by_identity([])
        self.assertEqual(len(result), 0)


class TestBuildExportUrl(unittest.TestCase):
    def test_standard_endpoint(self):
        url = build_export_url("https://example.com", "agent1", "tenant1")
        self.assertEqual(
            url,
            "https://example.com/observability/tenants/tenant1/otlp/agents/agent1/traces?api-version=1",
        )

    def test_s2s_endpoint(self):
        url = build_export_url("https://example.com", "agent1", "tenant1", use_s2s_endpoint=True)
        self.assertIn("/observabilityService/", url)

    def test_domain_without_scheme(self):
        url = build_export_url("example.com", "agent1", "tenant1")
        self.assertTrue(url.startswith("https://example.com/"))


class TestGetValidatedDomainOverride(unittest.TestCase):
    def test_not_set(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_validated_domain_override())

    def test_valid_https(self):
        with unittest.mock.patch.dict(
            os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": "https://custom.endpoint.com"}
        ):
            self.assertEqual(get_validated_domain_override(), "https://custom.endpoint.com")

    def test_invalid_scheme(self):
        with unittest.mock.patch.dict(os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": "ftp://custom.endpoint.com"}):
            self.assertIsNone(get_validated_domain_override())

    def test_domain_with_path(self):
        with unittest.mock.patch.dict(os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": "example.com/path"}):
            self.assertIsNone(get_validated_domain_override())

    def test_empty(self):
        with unittest.mock.patch.dict(os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": ""}):
            self.assertIsNone(get_validated_domain_override())

    def test_plain_domain(self):
        with unittest.mock.patch.dict(os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": "custom.endpoint.com"}):
            self.assertEqual(get_validated_domain_override(), "custom.endpoint.com")

    def test_domain_with_port(self):
        with unittest.mock.patch.dict(os.environ, {"A365_OBSERVABILITY_DOMAIN_OVERRIDE": "custom.endpoint.com:8080"}):
            self.assertEqual(get_validated_domain_override(), "custom.endpoint.com:8080")


class TestParseRetryAfter(unittest.TestCase):
    def test_numeric(self):
        self.assertEqual(parse_retry_after({"Retry-After": "30"}), 30.0)

    def test_float(self):
        self.assertEqual(parse_retry_after({"Retry-After": "1.5"}), 1.5)

    def test_absent(self):
        self.assertIsNone(parse_retry_after({}))

    def test_http_date_ignored(self):
        self.assertIsNone(parse_retry_after({"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}))


class TestIsAgent365ExporterEnabled(unittest.TestCase):
    def test_enabled_true(self):
        with unittest.mock.patch.dict(os.environ, {"ENABLE_A365_OBSERVABILITY_EXPORTER": "true"}):
            self.assertTrue(is_agent365_exporter_enabled())

    def test_enabled_one(self):
        with unittest.mock.patch.dict(os.environ, {"ENABLE_A365_OBSERVABILITY_EXPORTER": "1"}):
            self.assertTrue(is_agent365_exporter_enabled())

    def test_disabled_false(self):
        with unittest.mock.patch.dict(os.environ, {"ENABLE_A365_OBSERVABILITY_EXPORTER": "false"}):
            self.assertFalse(is_agent365_exporter_enabled())

    def test_not_set(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_agent365_exporter_enabled())


class TestFicTokenResolverTimeout(unittest.TestCase):
    """Verify FIC token resolver passes timeout to MSAL and handles missing msal."""

    FIC_ENV = {
        "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID": "test-client-id",
        "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET": "test-secret",
        "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID": "test-tenant",
        "A365_AGENT_APP_INSTANCE_ID": "test-instance-id",
        "A365_AGENTIC_USER_ID": "test-user-id",
    }

    def test_msal_apps_created_with_timeout(self):
        """Both ConfidentialClientApplication instances receive timeout parameter."""
        from microsoft.opentelemetry.a365.constants import A365_HTTP_TIMEOUT_SECONDS

        mock_msal = MagicMock()
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "access_token": "fake-token",
            "expires_in": 3600,
        }
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        with unittest.mock.patch.dict("sys.modules", {"msal": mock_msal}):
            from microsoft.opentelemetry.a365.core.exporters.utils import _create_fic_token_resolver

            resolver = _create_fic_token_resolver()

        with unittest.mock.patch.dict(os.environ, self.FIC_ENV):
            resolver("agent-id", "tenant-id")

        calls = mock_msal.ConfidentialClientApplication.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call.kwargs["timeout"], A365_HTTP_TIMEOUT_SECONDS)

    def test_msal_not_installed_returns_none(self):
        """Resolver returns None gracefully when msal is not installed."""
        # Temporarily remove msal from modules to simulate ImportError
        with unittest.mock.patch.dict("sys.modules", {"msal": None}):
            # Need to force re-import of the factory
            import importlib
            import microsoft.opentelemetry.a365.core.exporters.utils as utils_mod

            importlib.reload(utils_mod)
            resolver = utils_mod._create_fic_token_resolver()

        with unittest.mock.patch.dict(os.environ, self.FIC_ENV):
            result = resolver("agent-id", "tenant-id")

        self.assertIsNone(result)

        # Reload to restore normal state
        import importlib
        import microsoft.opentelemetry.a365.core.exporters.utils as utils_mod

        importlib.reload(utils_mod)


if __name__ == "__main__":
    unittest.main()
