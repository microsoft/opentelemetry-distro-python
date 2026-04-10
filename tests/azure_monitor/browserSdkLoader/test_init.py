# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

import unittest
from unittest.mock import MagicMock, patch

from microsoft.opentelemetry._azure_monitor._browser_sdk_loader._config import BrowserSDKConfig

_MW_PATH = (
    "microsoft.opentelemetry._azure_monitor._browser_sdk_loader"
    ".django_middleware.ApplicationInsightsWebSnippetMiddleware"
)


class TestSetupSnippetInjection(unittest.TestCase):
    def setUp(self):
        self.config = BrowserSDKConfig(
            enabled=True,
            connection_string="InstrumentationKey=test;IngestionEndpoint=https://test.in.ai.azure.com/",
        )

    @patch("microsoft.opentelemetry._azure_monitor._browser_sdk_loader._setup_django_injection")
    def test_setup_snippet_injection_calls_django(self, mock_django):
        from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import setup_snippet_injection

        setup_snippet_injection(self.config)
        mock_django.assert_called_once_with(self.config)

    @patch(
        "microsoft.opentelemetry._azure_monitor._browser_sdk_loader._setup_django_injection",
        side_effect=Exception("boom"),
    )
    def test_setup_snippet_injection_handles_exception(self, mock_django):
        from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import setup_snippet_injection

        # Should not raise
        setup_snippet_injection(self.config)


class TestSetupDjangoInjection(unittest.TestCase):
    def setUp(self):
        self.config = BrowserSDKConfig(
            enabled=True,
            connection_string="InstrumentationKey=test;IngestionEndpoint=https://test.in.ai.azure.com/",
        )

    @patch.dict("sys.modules", {"django": None, "django.conf": None})
    def test_django_not_available(self):
        from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _setup_django_injection

        # Should not raise when django is not importable
        _setup_django_injection(self.config)

    @patch("microsoft.opentelemetry._azure_monitor._browser_sdk_loader._register_django_middleware")
    def test_django_available_and_configured(self, mock_register):
        settings_mock = MagicMock()
        settings_mock.configured = True

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _setup_django_injection

            _setup_django_injection(self.config)
            mock_register.assert_called_once_with(self.config)

    def test_django_not_configured(self):
        settings_mock = MagicMock()
        settings_mock.configured = False

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _setup_django_injection

            # Should return early without raising
            _setup_django_injection(self.config)


class TestRegisterDjangoMiddleware(unittest.TestCase):
    def setUp(self):
        self.config = BrowserSDKConfig(
            enabled=True,
            connection_string="InstrumentationKey=test;IngestionEndpoint=https://test.in.ai.azure.com/",
        )

    def test_register_with_middleware_attr(self):
        settings_mock = MagicMock(spec_set=["MIDDLEWARE"])
        settings_mock.MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _register_django_middleware

            _register_django_middleware(self.config)
            # Our middleware should have been appended
            middleware_list = settings_mock.MIDDLEWARE
            self.assertIn(_MW_PATH, middleware_list)

    def test_register_with_middleware_classes_attr(self):
        settings_mock = MagicMock(spec=[])
        settings_mock.MIDDLEWARE_CLASSES = ["django.middleware.common.CommonMiddleware"]

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _register_django_middleware

            _register_django_middleware(self.config)
            self.assertIn(_MW_PATH, settings_mock.MIDDLEWARE_CLASSES)

    def test_already_registered(self):
        middleware_path = _MW_PATH
        settings_mock = MagicMock()
        settings_mock.MIDDLEWARE = [middleware_path]

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _register_django_middleware

            _register_django_middleware(self.config)
            # Should not duplicate
            self.assertEqual(settings_mock.MIDDLEWARE.count(middleware_path), 1)


class TestStoreDjangoConfig(unittest.TestCase):
    def setUp(self):
        self.config = BrowserSDKConfig(
            enabled=True,
            connection_string="InstrumentationKey=test;IngestionEndpoint=https://test.in.ai.azure.com/",
        )

    def test_store_config(self):
        settings_mock = MagicMock(spec=[])
        # No AZURE_MONITOR_WEB_SNIPPET_CONFIG attribute yet

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _store_django_config

            _store_django_config(self.config)
            self.assertEqual(settings_mock.AZURE_MONITOR_WEB_SNIPPET_CONFIG, self.config)

    def test_store_config_already_set(self):
        existing_config = BrowserSDKConfig(enabled=False)
        settings_mock = MagicMock()
        settings_mock.AZURE_MONITOR_WEB_SNIPPET_CONFIG = existing_config

        with patch.dict(
            "sys.modules",
            {
                "django": MagicMock(),
                "django.conf": MagicMock(settings=settings_mock),
            },
        ):
            from microsoft.opentelemetry._azure_monitor._browser_sdk_loader import _store_django_config

            _store_django_config(self.config)
            # Should not overwrite
            self.assertEqual(settings_mock.AZURE_MONITOR_WEB_SNIPPET_CONFIG, existing_config)
