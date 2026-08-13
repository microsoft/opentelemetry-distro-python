# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Foundry Responses API sample.

For an Azure AI Foundry deployment called via LangChain's ``ChatOpenAI`` with
the Responses API, set ``include_response_headers=True``. Foundry only reports
the served model snapshot in the ``x-ms-served-model`` response header, so this
flag is what lets the distro's LangChain instrumentation record the correct
``gen_ai.response.model`` on the span.
"""

import os

from microsoft.opentelemetry import use_microsoft_opentelemetry

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

MODEL_NAME = "gpt-4.1-deployment-for-langchain"
API_KEY = os.environ["AZURE_OPENAI_API_KEY"]
BASE_URL = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/"


def main() -> None:
    use_microsoft_opentelemetry(
        enable_azure_monitor=True,
        sampling_ratio=1.0,
        enable_sensitive_data=True,
    )

    llm = ChatOpenAI(
        model=MODEL_NAME,
        base_url=BASE_URL,
        api_key=API_KEY,
        use_responses_api=True,
        # Required so gen_ai.response.model reflects the served model. Langchain documentation - https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/include_response_headers
        include_response_headers=True,
    )

    result = llm.invoke(
        [
            SystemMessage(content="You are a concise, helpful assistant."),
            HumanMessage(content="In one sentence, what is OpenTelemetry?"),
        ]
    )
    print(result.content)


if __name__ == "__main__":
    main()
