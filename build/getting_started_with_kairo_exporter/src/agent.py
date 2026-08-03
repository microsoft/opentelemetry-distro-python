# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import logging
from os import environ

from dotenv import load_dotenv
from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import (
    AgentApplication,
    Authorization,
    MemoryStorage,
    TurnContext,
    TurnState,
)
from microsoft_agents.hosting.core.storage import (
    ConsoleTranscriptLogger,
    TranscriptLoggerMiddleware,
)
from microsoft.opentelemetry.a365.core import (
    AgentDetails as GuardrailAgentDetails,
    Request as GuardrailRequest,
)
from microsoft_agents_a365.observability.core.invoke_agent_details import InvokeAgentScopeDetails
from microsoft_agents_a365.observability.core.invoke_agent_scope import InvokeAgentScope
from microsoft_agents_a365.observability.core.middleware.baggage_builder import BaggageBuilder
from microsoft_agents_a365.observability.core.models.response import Response
from microsoft_agents_a365.observability.core.spans_scopes.output_scope import OutputScope
from microsoft_agents_a365.observability.hosting.token_cache_helpers import (
    AgenticTokenStruct,
)
from microsoft_agents_a365.runtime.environment_utils import (
    get_observability_authentication_scope,
)
from services.guardrail_service import evaluate_input_guardrail
from services.openai_service import call_azure_openai
from services.tool_service import execute_tool
from utils.observability_helpers import (
    create_agent_details,
    create_request_details,
)
from utils.token_cache import cache_agentic_token

logger = logging.getLogger(__name__)

load_dotenv()
agents_sdk_config = load_configuration_from_env(environ)


STORAGE = MemoryStorage()
CONNECTION_MANAGER = MsalConnectionManager(**agents_sdk_config)
ADAPTER = CloudAdapter(connection_manager=CONNECTION_MANAGER)
ADAPTER.use(TranscriptLoggerMiddleware(ConsoleTranscriptLogger()))
AUTHORIZATION = Authorization(STORAGE, CONNECTION_MANAGER, **agents_sdk_config)

AGENT_APP = AgentApplication[TurnState](
    storage=STORAGE, adapter=ADAPTER, authorization=AUTHORIZATION, **agents_sdk_config
)

# Token cache will be injected via adapter.app_context by start_server


def _get_token_cache():
    """Get token cache from application context (injected by start_server)."""
    if hasattr(ADAPTER, "app_context") and "token_cache" in ADAPTER.app_context:
        return ADAPTER.app_context["token_cache"]
    return None


@AGENT_APP.activity("message", auth_handlers=["AGENTIC"])
async def on_message(context: TurnContext, _state: TurnState):
    """Handle incoming messages and respond using Azure OpenAI."""
    agent_details = create_agent_details(context)

    # Register observability token cache using injected AgenticTokenCache
    token_cache = _get_token_cache()
    if token_cache:
        token_struct = AgenticTokenStruct(
            authorization=AGENT_APP.auth,
            turn_context=context,
            auth_handler_name="AGENTIC",
        )

        token_cache.register_observability(
            agent_id=agent_details.agent_id,
            tenant_id=agent_details.tenant_id,
            token_generator=token_struct,
            observability_scopes=get_observability_authentication_scope(),
        )
    else:
        logger.warning("Token cache not available in app context")

    # Create invoke agent scope details
    invoke_scope_details = InvokeAgentScopeDetails()

    # Get the user's message early for request details
    user_message = context.activity.text
    if not user_message:
        await context.send_activity("I didn't receive any message text to process.")
        return

    # Create request details
    request_details = create_request_details(
        user_message, context.activity.conversation.id if context.activity.conversation else None
    )

    try:
        # with (
        #     BaggageBuilder()
        #     .correlation_id("7ff6dca0-917c-4bb0-b31a-794e533d8aad")
        #     .user_id(context.activity.from_property.aad_object_id)
        #     .user_name(context.activity.from_property.name)
        #     .user_email("Sample UPN")
        #     .build()
        # ):
        # Start invoke agent scope for observability
        invoke_scope = InvokeAgentScope.start(
            request=request_details,
            scope_details=invoke_scope_details,
            agent_details=agent_details,
        )

        try:
            with invoke_scope:
                # Get the agentic user token with observability scope
                invoke_scope.record_input_messages([user_message])
                guardrail_result = evaluate_input_guardrail(
                    user_message=user_message,
                    agent_details=GuardrailAgentDetails(
                        agent_id=agent_details.agent_id,
                        agent_name=agent_details.agent_name,
                        tenant_id=agent_details.tenant_id,
                    ),
                    request=GuardrailRequest(
                        conversation_id=(
                            context.activity.conversation.id
                            if context.activity.conversation
                            else None
                        ),
                    ),
                )
                if not guardrail_result.allowed:
                    await context.send_activity(guardrail_result.response_message)
                    return

                exaau_token = await AGENT_APP.auth.exchange_token(
                    context,
                    scopes=get_observability_authentication_scope(),
                    auth_handler_id="AGENTIC",
                )

                # Cache the agentic token for exporter use (old approach - for reference)
                cache_agentic_token(
                    agent_details.tenant_id, agent_details.agent_id, exaau_token.token
                )

                logger.info(f"Processing user message: {user_message}")

                # Demo: Execute a tool if user asks about weather or calculations
                tool_result = None
                if "weather" in user_message.lower():
                    tool_result = await execute_tool("get_weather", "current location", context)
                elif "calculate" in user_message.lower() or "math" in user_message.lower():
                    tool_result = await execute_tool("calculate", "2 + 2", context)

                # Call Azure OpenAI with inference scope tracing
                enhanced_message = user_message
                if tool_result:
                    enhanced_message = f"{user_message}\n\nTool result: {tool_result}"

                ai_response = await call_azure_openai(enhanced_message, context)

                # Send the AI response back to the user
                await context.send_activity(ai_response)

            # Record output in a separate OutputScope outside the invoke scope,
            # linked to the invoke scope via parent_id
            invoke_span = invoke_scope._span
            if invoke_span and invoke_span.context:
                parent_id = (
                    f"00-{invoke_span.context.trace_id:032x}-{invoke_span.context.span_id:016x}-01"
                )
            else:
                parent_id = None

            # now handled with middleware, but keeping this here for reference on how to link spans with parent_id
            # with OutputScope.start(
            #     request=Request(),
            #     response=Response(messages=[ai_response]),
            #     agent_details=agent_details,
            # ):
            #     pass

        except Exception as e:
            logger.error(f"Error in on_message: {e}")
            invoke_scope.record_error(e)
            await context.send_activity(
                "I encountered an error while processing your message. Please try again."
            )
    except Exception as e:
        logger.error(f"Error setting up observability scope: {e}")


@AGENT_APP.error
async def on_error(context: TurnContext, error: Exception):
    logger.error("[on_turn_error] unhandled error: %s", error)

    # Send a message to the user
    await context.send_activity("The agent encountered an error.")
