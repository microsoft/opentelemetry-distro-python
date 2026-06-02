# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Build a default :class:`StatsbeatConfig` for the distro standalone path.

When the distro is configured without Azure Monitor (OTLP-only, A365-only,
Console-only) the customer never instantiates an
``AzureMonitorMetricExporter``, so the upstream :class:`StatsbeatManager`
has no exporter to derive its config from.  This helper builds a synthetic
:class:`StatsbeatConfig` pointing at the well-known statsbeat ingestion
endpoint so SDKStats can still be emitted in those modes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from microsoft.opentelemetry._version import VERSION

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from azure.monitor.opentelemetry.exporter.statsbeat._manager import StatsbeatConfig

# Region label used when SDKStats runs standalone (no customer exporter, so
# no customer endpoint to derive a region from).  Upstream requires a
# non-empty region to validate the config.
_SDKSTATS_DEFAULT_REGION = "n/a"

def _build_default_sdkstats_config() -> Optional["StatsbeatConfig"]:
    """Return a default upstream ``StatsbeatConfig`` or ``None`` on failure."""
    try:
        from azure.monitor.opentelemetry.exporter._connection_string_parser import (
            ConnectionStringParser,
        )
        from azure.monitor.opentelemetry.exporter.statsbeat._manager import (
            StatsbeatConfig,
        )
        from azure.monitor.opentelemetry.exporter.statsbeat._utils import (
            _get_stats_connection_string,
        )
    except ImportError:
        logger.debug("Upstream statsbeat package unavailable; skipping SDKStats config.")
        return None

    # Upstream will return the default statsbeat connection string.
    conn_str = _get_stats_connection_string("")

    try:
        parsed = ConnectionStringParser(conn_str)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Failed to parse default statsbeat connection string.")
        return None

    if not parsed.instrumentation_key or not parsed.endpoint:
        return None

    return StatsbeatConfig(
        endpoint=parsed.endpoint,
        region=parsed.region or _SDKSTATS_DEFAULT_REGION,
        instrumentation_key=parsed.instrumentation_key,
        # Standalone (no Azure Monitor) — the customer has not opted into
        # Azure Monitor's offline disk-retry storage, so suppress upstream's
        # DISK_RETRY feature bit (which would otherwise be OR'd in by
        # ``_StatsbeatMetrics.__init__``).
        disable_offline_storage=True,
        distro_version=VERSION,
        connection_string=conn_str,
    )
