# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

# --- Microsoft Distro Overrides ---

# The microsoft distro uses a different connection string parameter name
# to distinguish it from the azure-monitor-opentelemetry "connection_string"
# parameter. The microsoft distro remaps this to "connection_string" when
# delegating to configure_azure_monitor().
CONNECTION_STRING_ARG = "azure_monitor_connection_string"

# Azure Monitor Exporter
DISABLE_AZURE_MONITOR_EXPORTER_ARG = "disable_azure_monitor_exporter"
