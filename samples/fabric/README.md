# Fabric / Azure Data Explorer Sample

Sends traces, metrics, and logs through an OpenTelemetry Collector to Microsoft Fabric or Azure Data Explorer.

## Prerequisites

- Python 3.10+
- `microsoft-opentelemetry` installed (`pip install .` from repo root)
- An [OTel Collector Contrib](https://github.com/open-telemetry/opentelemetry-collector-releases/releases) binary or Docker image
- A Fabric KQL database or Azure Data Explorer cluster with tables created (see [full guide](../../docs/fabric-getting-started.md))

## Run

1. Update `collector-config.yaml` with your cluster URI and database name.

2. Start the collector:

   ```bash
   # Binary
   otelcol-contrib --config collector-config.yaml

   # Docker
   docker run --rm -p 4317:4317 -p 4318:4318 \
     -v ${PWD}/samples/fabric/collector-config.yaml:/etc/otelcol-contrib/config.yaml \
     otel/opentelemetry-collector-contrib:0.121.0
   ```

3. In another terminal, run the sample:

   ```bash
   # Windows
   set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
   python samples/fabric/app.py

   # Linux / macOS
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python samples/fabric/app.py
   ```

4. Query your ADX/Fabric tables to verify data arrived:

   ```kql
   OTELTraces | take 10
   OTELLogs | take 10
   OTELMetrics | take 10
   ```

## Full Guide

See [docs/fabric-getting-started.md](../../docs/fabric-getting-started.md) for the complete step-by-step walkthrough including table creation, permissions, and authentication options.
