import os
from azure.monitor.opentelemetry import configure_azure_monitor

os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"

configure_azure_monitor() # TODO: Replace with the new distro configuration

from opentelemetry.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from agents import Agent, Runner, function_tool
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncAzureOpenAI, OpenAI

OpenAIAgentsInstrumentor().instrument()

# If using Azure OpenAI, set the endpoint, API key, if using OPENAI_API_KEY environment variable, you can skip this
_endpoint = "<AZURE_OPENAI_ENDPOINT>"
_api_key = "<AZURE_OPENAI_API_KEY>"

@function_tool
def get_attractions(city: str) -> str:
    """Get popular attractions and things to do in a city."""
    attractions = {
        "reno": (
            "Top things to do in Reno:\n"
            "1. The Riverwalk District - shops, restaurants along Truckee River\n"
            "2. National Automobile Museum - 200+ vintage cars\n"
            "3. Lake Tahoe (30 min drive) - hiking, skiing, beaches\n"
            "4. Circus Circus Midway - family entertainment\n"
            "5. Nevada Museum of Art"
        ),
        "san jose": (
            "Top things to do in San Jose:\n"
            "1. The Tech Interactive - science museum\n"
            "2. San Jose Municipal Rose Garden\n"
            "3. Winchester Mystery House\n"
            "4. Santana Row - shopping and dining\n"
            "5. Japanese Friendship Garden"
        ),
    }
    return attractions.get(city.lower(), f"No attraction info available for {city}.")


def run_agent() -> None:
    """Create a simple agent and execute a single run."""

    # If using Azure OpenAI, create an AsyncAzureOpenAI client, else skip this part
    azure_model = OpenAIChatCompletionsModel(
        model="gpt-4.1",
        openai_client=AsyncAzureOpenAI(
            azure_endpoint=_endpoint,
            api_key=_api_key,
        ),
    )

    assistant = Agent(
        name="Travel Planner",
        instructions=(
            "You are a friendly travel planner. Use the get_attractions tool to find "
            "things to do and plan a simple itinerary for the user's trip."
        ),
        tools=[get_attractions],
        model=azure_model, # If using OPENAI_API_KEY, you can remove this parameter
    )

    result = Runner.run_sync(
        assistant,
        "Plan a weekend trip from San Jose to Reno. What should I do there?",
    )

    print("Agent response:")
    print(result.final_output)


if __name__ == "__main__":
    run_agent()
