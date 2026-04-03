# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Integration tests for the microsoft.opentelemetry distro package.

Validates public API surface, Azure Monitor delegation, environment variable
handling, and error paths.
"""

import os
import unittest
from unittest.mock import patch

from microsoft.opentelemetry._configure import (
    _setup_azure_monitor,
    configure_microsoft_opentelemetry,
)

TEST_CONNECTION_STRING = (
    "InstrumentationKey=test-key;" + "IngestionEndpoint=https://test.in.ai.azure.com/"
)


# -- Public API Surface ---------------------------------------------------


class TestPublicAPISurface(unittest.TestCase):
    """Validate that the package exposes the intended public API."""

    def test_configure_importable_from_package_root(self):
        from microsoft.opentelemetry import configure_microsoft_opentelemetry as fn

        self.assertTrue(callable(fn))

    def test_version_accessible(self):
        from microsoft.opentelemetry import __version__

        self.assertIsInstance(__version__, str)
        self.assertTrue(len(__version__) > 0)

    def test_all_exports_only_configure(self):
        from microsoft.opentelemetry import __all__

        self.assertEqual(__all__, ["configure_microsoft_opentelemetry"])

    def test_constants_reexported(self):
        from microsoft.opentelemetry._constants import CONNECTION_STRING_ARG

        self.assertIsInstance(CONNECTION_STRING_ARG, str)

    def test_types_reexported(self):
        from microsoft.opentelemetry._types import ConfigurationValue

        self.assertIsNotNone(ConfigurationValue)


# -- Azure Monitor Error Handling ------------------------------------------


class TestAzureMonitorImportError(unittest.TestCase):
    """Tests for _setup_azure_monitor import error handling."""

    def test_warns_when_azure_monitor_not_installed(self):
        with patch.dict("sys.modules", {"azure.monitor.opentelemetry": None}):
            with self.assertLogs(
                "microsoft.opentelemetry._configure", level="WARNING"
            ) as cm:
                _setup_azure_monitor(connection_string=TEST_CONNECTION_STRING)
            self.assertTrue(
                any("not installed" in msg for msg in cm.output),
            )


# -- Environment Variable Handling -----------------------------------------


class TestEnvironmentVariableConfiguration(unittest.TestCase):
    """Tests for env var driven configuration."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_connection_string_env_var_enables_azure_monitor(self, az_mock):
        env = {"APPLICATIONINSIGHTS_CONNECTION_STRING": TEST_CONNECTION_STRING}
        with patch.dict(os.environ, env, clear=False):
            configure_microsoft_opentelemetry()
        az_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_no_connection_string_logs_info(self, az_mock):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
            with self.assertLogs(
                "microsoft.opentelemetry._configure", level="INFO"
            ) as cm:
                configure_microsoft_opentelemetry()
        az_mock.assert_not_called()
        self.assertTrue(any("not configured" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
