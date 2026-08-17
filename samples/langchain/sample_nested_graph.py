# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Nested graph sample.

An outer compiled graph ("OuterWorkflow") runs two nodes:

- Compiled agent (``create_agent``) used as a node: auto-detected as its own
  ``invoke_agent`` span. Nothing extra is needed.
- Plain function node (not a create_agent): NOT an agent boundary, so it gets no
  ``invoke_agent`` span on its own. Attach ``metadata={"agent_name": ...}`` on
  ``add_node`` to give it a named agent span (its LLM call then nests under it).
  Drop that metadata and the node's LLM call shows up with no agent span.
"""

import asyncio
import os

from microsoft.opentelemetry import use_microsoft_opentelemetry

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState

MODEL_NAME = "gpt-4o"
API_KEY = os.environ["AZURE_OPENAI_API_KEY"]
BASE_URL = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/"


def main() -> None:
    use_microsoft_opentelemetry(
        enable_azure_monitor=True,
        sampling_ratio=1.0,
        enable_sensitive_data=True,
    )

    def chat_model():
        return ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            base_url=os.environ.get("AZURE_OPENAI_ENDPOINT") + "openai/v1",
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        )

    async def compiled_node(state: MessagesState, config: RunnableConfig):
        resp = await chat_model().ainvoke(
            [HumanMessage(content="In one sentence, say why Paris is worth visiting.")],
            config=config,
        )
        return {"messages": [resp]}

    inner_graph = (
        StateGraph(MessagesState)
        .add_node(
            "compiled", compiled_node, metadata={"agent_name": "CompiledAgent"}
        )  # This is needed to identify the invoke agent span for the inner nested subggraph.
        .add_edge(START, "compiled")
        .add_edge("compiled", END)
        .compile(name="InnerWorkflow")
    )

    graph = (
        StateGraph(MessagesState)
        .add_node("builder", inner_graph)
        .add_edge(START, "builder")
        .add_edge("builder", END)
        .compile(name="OuterWorkflow")
    )

    result = asyncio.run(
        graph.ainvoke({"messages": [HumanMessage(content="What is the capital of France?")]}),
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
