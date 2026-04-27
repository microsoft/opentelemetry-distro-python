# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""OTLP export sample — sends traces to an OTLP-compatible collector.

Before running, set the OTLP endpoint environment variable:

    set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

Then run:

    python samples/otlp/tracing.py
"""

import os
import time

from opentelemetry import trace

from microsoft.opentelemetry import use_microsoft_opentelemetry

os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

use_microsoft_opentelemetry()

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("otlp-sample") as span:
    span.set_attribute("sample.name", "otlp-tracing")
    print("Sending trace via OTLP...")
    time.sleep(0.1)

    with tracer.start_as_current_span("child-operation") as child:
        child.set_attribute("operation", "process")
        time.sleep(0.05)

print("Traces sent to OTLP endpoint. Press Enter to exit...")
input()
