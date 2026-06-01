# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------


from azure.monitor.opentelemetry.exporter._constants import (  # type: ignore[import-not-found]
    _REQ_SUCCESS_NAME,
)

REQUEST_SUCCESS_NAME = _REQ_SUCCESS_NAME[0]


# Endpoint type enum values for the ``endpoint`` dimension on network sdkstats
# metrics.  Per spec the value must be one of these strings.
ENDPOINT_BREEZE = "breeze"
ENDPOINT_OTLP = "otlp"
ENDPOINT_A365 = "a365"
