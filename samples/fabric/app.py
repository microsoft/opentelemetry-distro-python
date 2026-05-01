# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Fabric / Azure Data Explorer export sample.

Sends traces, metrics, and logs to an OTLP-compatible collector configured
with the Azure Data Explorer exporter. See docs/fabric-getting-started.md
for the full walkthrough.

Before running, set the OTLP endpoint environment variable:

    set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

Then run:

    python samples/fabric/app.py
"""

import logging
import time

from opentelemetry import trace, metrics
from microsoft.opentelemetry import use_microsoft_opentelemetry

LOGGER_NAME = "fabric-demo"

use_microsoft_opentelemetry(logger_name=LOGGER_NAME)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(LOGGER_NAME)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

request_counter = meter.create_counter(
    "app.requests",
    description="Number of requests processed",
)

logger.info("App started — sending telemetry to OTLP collector")

for i in range(5):
    with tracer.start_as_current_span("process-request") as span:
        span.set_attribute("request.id", i)
        request_counter.add(1, {"request.type": "demo"})
        logger.info("Processing request %d", i)
        time.sleep(0.5)

logger.info("Done. Waiting for export flush...")
time.sleep(5)
