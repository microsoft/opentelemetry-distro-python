# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Integration tests for the microsoft.opentelemetry distro package.

Validates public API surface, Azure Monitor delegation, environment variable
handling, and error paths.
"""

import unittest
from unittest.mock import patch

from microsoft.opentelemetry._configure import (
    _setup_azure_monitor,
    configure_microsoft_opentelemetry,
)

TEST_CONNECTION_STRING = "InstrumentationKey=test-key;" + "IngestionEndpoint=https://test.in.ai.azure.com/"


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
        from microsoft.opentelemetry._constants import (
            DISABLE_AZURE_MONITOR_EXPORTER_ARG,
        )

        self.assertIsInstance(DISABLE_AZURE_MONITOR_EXPORTER_ARG, str)

    def test_types_reexported(self):
        from microsoft.opentelemetry._types import ConfigurationValue

        self.assertIsNotNone(ConfigurationValue)


# -- Azure Monitor Error Handling ------------------------------------------


class TestAzureMonitorImportError(unittest.TestCase):
    """Tests for _setup_azure_monitor import error handling."""

    def test_warns_when_azure_monitor_not_installed(self):
        with patch.dict("sys.modules", {"azure.monitor.opentelemetry": None}):
            with self.assertLogs("microsoft.opentelemetry._configure", level="WARNING") as cm:
                _setup_azure_monitor(connection_string=TEST_CONNECTION_STRING)
            self.assertTrue(
                any("not installed" in msg for msg in cm.output),
            )


# -- Default Behavior -------------------------------------------------------


class TestDefaultBehavior(unittest.TestCase):
    """Tests that Azure Monitor is enabled by default."""

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_enabled_by_default_no_args(self, az_mock):
        configure_microsoft_opentelemetry()
        az_mock.assert_called_once()

    @patch("microsoft.opentelemetry._configure._setup_azure_monitor")
    def test_disabled_when_explicitly_set(self, az_mock):
        configure_microsoft_opentelemetry(
            disable_azure_monitor_exporter=True,
        )
        az_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
