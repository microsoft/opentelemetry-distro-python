# OTLP Export Sample

Sends traces to an OTLP-compatible collector using `microsoft-opentelemetry` with Azure Monitor disabled.

## Prerequisites

- Docker (for the local collector)
- `microsoft-opentelemetry` installed (`pip install .` from repo root)

## Run

1. Start a local OpenTelemetry Collector:

   ```
   docker run --rm -p 4318:4318 -v ${PWD}/samples/otlp/collector-config.yaml:/etc/otelcol/config.yaml otel/opentelemetry-collector:latest
   ```

2. In another terminal, run the sample:

   ```
   python samples/otlp/tracing.py
   ```

3. Observe trace output in the collector terminal.

## Configuration

The sample defaults to `http://localhost:4318`. Override with:

```
set OTEL_EXPORTER_OTLP_ENDPOINT=http://your-collector:4318
python samples/otlp/tracing.py
```
