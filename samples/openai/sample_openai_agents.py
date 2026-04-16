# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Sample: OpenAI Agents SDK with Microsoft OpenTelemetry Distro.

Prerequisites:
    pip install microsoft-opentelemetry openai-agents

Environment variables:
    APPLICATIONINSIGHTS_CONNECTION_STRING  – Azure Monitor connection string
    OPENAI_API_KEY                         – OpenAI API key
"""

import os

from agents import Agent, Runner, function_tool
from microsoft.opentelemetry import use_microsoft_opentelemetry

# Connection string can also be passed directly:
# azure_monitor_connection_string="InstrumentationKey=..."
use_microsoft_opentelemetry(
    azure_monitor_connection_string=os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", ""),
)


@function_tool
def get_weather(city: str) -> str:
    """Return a mock weather forecast for a city."""
    return f"The weather in {city} is sunny, 25°C."


agent = Agent(
    name="Travel Concierge",
    instructions="You are a concise travel assistant. Answer in one or two sentences.",
    tools=[get_weather],
)

result = Runner.run_sync(agent, "What should I pack for Barcelona this weekend?")
print(result.final_output)
