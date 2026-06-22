# LangChain Samples

These samples demonstrate how to use LangChain with OpenTelemetry tracing exported to Azure Monitor (Application Insights).

## Prerequisites

- Python 3.10+
- An Azure OpenAI resource (or an OpenAI API key)
- An Application Insights resource (for the connection string)

## Configuration

All samples require you to fill in placeholder values before running.

## Samples

### 1. `sample_langchain_instrumentation.py`

Demonstrates the internal langchain instrumentation.

**Environment variables to set to view the telemetry**

| Environment Variable | Value |
| ---------------------------------------------------- | ---------------------------- |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | "SPAN_AND_EVENT"             |
| `OTEL_SEMCONV_STABILITY_OPT_IN`                      | "gen_ai_latest_experimental" |
| `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING`            | "true"                       |

> **Alternative** Instead of setting the `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` and `OTEL_SEMCONV_STABILITY_OPT_IN` environment variables, pass the config `enable_sensitive_data=True` to `use_microsoft_opentelemetry()`:

```python
use_microsoft_opentelemetry(
    enable_sensitive_data=True,
    ...
)
```

When `enable_sensitive_data=True` is supplied:

- Sensitive and experimental data attributes populate on the spans.
- The content capture mode defaults to `SPAN_AND_EVENT`.
- This setting takes **precedence over** the pre-existing values of the corresponding environment variables.

> **Note:** `enable_sensitive_data` defaults to `False`. Only enable it in trusted, non-production environments where capturing message content is intentional.

---

**Placeholders to fill: If use azure endpoint and api key**

| Placeholder | Value |
|---|---|
| `<AZURE_OPENAI_ENDPOINT>` | Azure OpenAI endpoint URL |
| `<AZURE_OPENAI_API_KEY>` | Azure OpenAI API key |


**Run:**
```bash
python sample_langchain_instrumentation.py
```