import os
os.environ["ENABLE_OBSERVABILITY"] = "true"

from azure.monitor.opentelemetry._configure import configure_azure_monitor
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent


endpoint = "https://azmondistro-resources.cognitiveservices.azure.com/openai/v1/"
model_name = "gpt-4.1"
deployment_name = "gpt-4.1"

api_key = "1ILaNEKUS3lWD6yFFz0XCDvGTqZ3OEDLDknPaDGN2PRqvlPjF2yHJQQJ99CDACHYHv6XJ3w3AAAAACOGHx8K"


# configure_azure_monitor sets up TracerProvider + Azure Monitor exporter
configure_azure_monitor(
    sampling_ratio=1.0,
    instrumentation_options={
        "langchain": {"enabled": True},
        "requests": {"enabled": False},
        "urllib": {"enabled": False},
        "urllib3": {"enabled": False},
        "httpx": {"enabled": False},
    }
)

def main():

    # ChatOpenAI
    llm = ChatOpenAI(
        model="gpt-4.1",
        temperature=0.1,
        max_tokens=100,
        top_p=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.5,
        stop_sequences=["\n", "Human:", "AI:"],
        seed=100,
        api_key=api_key,
        base_url=endpoint,
    )

    # --- Part 1: Direct LLM invoke ---
    messages = [
        SystemMessage(content="You are a helpful assistant!"),
        HumanMessage(content="What is the capital of France?"),
    ]

    result = llm.invoke(messages)
    print("LLM output:\n", result)

    # --- Part 2: Agent with tools (invoke_agent) ---
    @tool
    def get_population(city: str) -> str:
        """Get the population of a city."""
        populations = {
            "paris": "2.1 million",
            "london": "8.9 million",
            "tokyo": "14 million",
            "new york": "8.3 million",
        }
        return populations.get(city.lower(), f"Population data not available for {city}.")

    @tool
    def get_famous_landmark(city: str) -> str:
        """Get the most famous landmark in a city."""
        landmarks = {
            "paris": "Eiffel Tower",
            "london": "Big Ben",
            "tokyo": "Tokyo Tower",
            "new york": "Statue of Liberty",
        }
        return landmarks.get(city.lower(), f"No landmark info for {city}.")

    agent = create_agent(
        llm,
        tools=[get_population, get_famous_landmark],
        system_prompt="You are a helpful travel assistant. Use the tools to answer questions about cities.",
    )

    print("\n--- Agent run ---")
    user_input = "What is the population of Paris and what is its most famous landmark?"
    agent_result = agent.invoke({"messages": [("human", user_input)]})
    output = agent_result["messages"][-1].content
    print("Agent output:\n", output)




if __name__ == "__main__":
    main()