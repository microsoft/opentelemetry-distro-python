# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

# --- Microsoft Distro Constants ---

ENABLE_AZURE_MONITOR_ARG = "enable_azure_monitor"

# Mapping from azure_monitor_ prefixed public kwargs to internal
# configure_azure_monitor() kwargs.
_AZURE_MONITOR_KWARG_MAP = {
    "azure_monitor_connection_string": "connection_string",
    "azure_monitor_exporter_credential": "credential",
    "azure_monitor_enable_live_metrics": "enable_live_metrics",
    "azure_monitor_enable_performance_counters": "enable_performance_counters",
    "azure_monitor_exporter_disable_offline_storage": "disable_offline_storage",
    "azure_monitor_exporter_storage_directory": "storage_directory",
    "azure_monitor_browser_sdk_loader_config": "browser_sdk_loader_config",
}
