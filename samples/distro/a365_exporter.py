# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Sample: Agent365 exporter with LangChain instrumentation.

Demonstrates how to use the A365 exporter alongside Azure Monitor and OTLP
to send agent traces to the Agent365 observability endpoint.

Prerequisites (environment variables):
  - ENABLE_A365_OBSERVABILITY_EXPORTER=true
  - A365_TENANT_ID=<your tenant id>
  - A365_AGENT_ID=<your agent id>
  - Authenticate via DefaultAzureCredential (e.g. ``az login``)

"""

import os

from opentelemetry import trace

from microsoft.opentelemetry import use_microsoft_opentelemetry

# -- Initialize OpenTelemetry with A365 exporter ----------------------------

os.environ.setdefault("ENABLE_A365_OBSERVABILITY_EXPORTER", "true")
os.environ.setdefault("A365_TENANT_ID", "<YOUR_TENANT_ID>")
os.environ.setdefault("A365_AGENT_ID", "<YOUR_AGENT_ID>")

use_microsoft_opentelemetry(
    enable_azure_monitor=False,
    enable_a365=True,
)


# -- Run agent code (identity is stamped automatically) ---------------------

def main():
    tracer = trace.get_tracer("a365.sample")

    # No need to set baggage manually -- the distro stamps tenant_id and
    # agent_id on every span via the A365SpanProcessor.
    with tracer.start_as_current_span("invoke_agent Travel_Assistant") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")

        with tracer.start_as_current_span("chat gpt-4.1") as llm_span:
            llm_span.set_attribute("gen_ai.operation.name", "chat")
            llm_span.set_attribute("gen_ai.request.model", "gpt-4.1")
            llm_span.set_attribute("gen_ai.usage.input_tokens", 150)
            llm_span.set_attribute("gen_ai.usage.output_tokens", 75)
            print("  LLM call: chat gpt-4.1")

        with tracer.start_as_current_span("execute_tool get_population") as tool_span:
            tool_span.set_attribute("gen_ai.operation.name", "execute_tool")
            tool_span.set_attribute("gen_ai.tool.name", "get_population")
            print("  Tool call: get_population")
    print("\nTraces exported to Agent365 endpoint.")


if __name__ == "__main__":
    main()
