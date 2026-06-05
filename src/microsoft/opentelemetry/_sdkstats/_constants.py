# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------



from azure.monitor.opentelemetry.exporter._constants import (  # type: ignore[import-not-found]
    _REQ_DURATION_NAME,
    _REQ_EXCEPTION_NAME,
    _REQ_FAILURE_NAME,
    _REQ_RETRY_NAME,
    _REQ_SUCCESS_NAME,
    _REQ_THROTTLE_NAME,
    _THROTTLE_STATUS_CODES,
)

REQUEST_DURATION_NAME = _REQ_DURATION_NAME[0]
REQUEST_EXCEPTION_NAME = _REQ_EXCEPTION_NAME[0]
REQUEST_FAILURE_NAME = _REQ_FAILURE_NAME[0]
REQUEST_RETRY_NAME = _REQ_RETRY_NAME[0]
REQUEST_SUCCESS_NAME = _REQ_SUCCESS_NAME[0]
REQUEST_THROTTLE_NAME = _REQ_THROTTLE_NAME[0]

THROTTLE_STATUS_CODES = _THROTTLE_STATUS_CODES


# Endpoint type enum values for the ``endpoint`` dimension on network sdkstats
# metrics.  Per spec the value must be one of these strings.
ENDPOINT_BREEZE = "breeze"
ENDPOINT_OTLP = "otlp"
ENDPOINT_A365 = "a365"
