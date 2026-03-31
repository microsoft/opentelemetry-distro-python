# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

# Re-export ConfigurationValue from azure-monitor-opentelemetry to avoid duplication
from azure.monitor.opentelemetry._types import ConfigurationValue

__all__ = ["ConfigurationValue"]
