# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from microsoft.opentelemetry.a365.core import (
    GenAiRequestParameters,
    GenAiResponseParameters,
    InvokeAgentScopeDetails,
)


def test_invoke_agent_details_accepts_semantic_parameters():
    request = GenAiRequestParameters(model="gpt-4o", max_tokens=128)
    response = GenAiResponseParameters(input_tokens=10, output_tokens=4)
    details = InvokeAgentScopeDetails(
        request_parameters=request,
        response_parameters=response,
    )
    assert details.request_parameters is request
    assert details.response_parameters is response
