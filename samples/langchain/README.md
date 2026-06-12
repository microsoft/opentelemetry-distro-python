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

> **Alternative:** instead of exporting `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` and `OTEL_SEMCONV_STABILITY_OPT_IN`, you can pass the equivalent kwargs to `use_microsoft_opentelemetry(...)`:
>
> ```python
> use_microsoft_opentelemetry(
>     enable_experimental_mode=True,
>     capture_message_content="span_and_event",
> )
> ```
>

> When both kwargs are supplied, they take **precedence over** any pre-existing values of those environment variables. If only one of the two kwargs is supplied (or `enable_experimental_mode` is `False`), both env vars are left untouched.
>
> **Accepted values for `capture_message_content`** (case-insensitive, surrounding whitespace ignored):
>
> | Value | Effect |
> | --- | --- |
> | `span_only` | Content captured on span attributes only |
> | `event_only` | Content captured on log/event records only |
> | `span_and_event` | Content captured on both spans and events |
>
> Any other value is ignored (the env var is left untouched and a warning is logged).

**Placeholders to fill: If use azure endpoint and api key**

| Placeholder | Value |
|---|---|
| `<AZURE_OPENAI_ENDPOINT>` | Azure OpenAI endpoint URL |
| `<AZURE_OPENAI_API_KEY>` | Azure OpenAI API key |


**Run:**
```bash
python sample_langchain_instrumentation.py
```