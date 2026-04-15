# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Constants for Agent365 exporter integration.

Vendored subset from microsoft-agents-a365-observability-core constants.
Only includes constants required by the exporter, processors, and utilities.
"""

# --- Span operation names ---
INVOKE_AGENT_OPERATION_NAME = "invoke_agent"

# --- GenAI semantic conventions ---
GEN_AI_OPERATION_NAME_KEY = "gen_ai.operation.name"
GEN_AI_AGENT_ID_KEY = "gen_ai.agent.id"
GEN_AI_AGENT_NAME_KEY = "gen_ai.agent.name"
GEN_AI_AGENT_DESCRIPTION_KEY = "gen_ai.agent.description"
GEN_AI_AGENT_VERSION_KEY = "gen_ai.agent.version"
GEN_AI_AGENT_PLATFORM_ID_KEY = "microsoft.a365.agent.platform.id"
GEN_AI_CONVERSATION_ID_KEY = "gen_ai.conversation.id"
GEN_AI_CONVERSATION_ITEM_LINK_KEY = "microsoft.conversation.item.link"
GEN_AI_INPUT_MESSAGES_KEY = "gen_ai.input.messages"

# --- Agent identity / baggage ---
TENANT_ID_KEY = "microsoft.tenant.id"
GEN_AI_AGENT_AUID_KEY = "microsoft.agent.user.id"
GEN_AI_AGENT_EMAIL_KEY = "microsoft.agent.user.email"
GEN_AI_AGENT_BLUEPRINT_ID_KEY = "microsoft.a365.agent.blueprint.id"
SESSION_ID_KEY = "microsoft.session.id"
SESSION_DESCRIPTION_KEY = "microsoft.session.description"

# --- Human caller ---
USER_ID_KEY = "user.id"
USER_NAME_KEY = "user.name"
USER_EMAIL_KEY = "user.email"
GEN_AI_CALLER_CLIENT_IP_KEY = "client.address"

# --- Agent-to-Agent caller ---
GEN_AI_CALLER_AGENT_USER_ID_KEY = "microsoft.a365.caller.agent.user.id"
GEN_AI_CALLER_AGENT_EMAIL_KEY = "microsoft.a365.caller.agent.user.email"
GEN_AI_CALLER_AGENT_NAME_KEY = "microsoft.a365.caller.agent.name"
GEN_AI_CALLER_AGENT_ID_KEY = "microsoft.a365.caller.agent.id"
GEN_AI_CALLER_AGENT_APPLICATION_ID_KEY = "microsoft.a365.caller.agent.blueprint.id"
GEN_AI_CALLER_AGENT_PLATFORM_ID_KEY = "microsoft.a365.caller.agent.platform.id"
GEN_AI_CALLER_AGENT_VERSION_KEY = "microsoft.a365.caller.agent.version"

# --- OTel standard keys ---
SERVER_ADDRESS_KEY = "server.address"
SERVER_PORT_KEY = "server.port"
SERVICE_NAME_KEY = "service.name"

# --- Custom span keys ---
CUSTOM_PARENT_SPAN_ID_KEY = "custom.parent.span.id"
CUSTOM_SPAN_NAME_KEY = "custom.span.name"

# --- Channel ---
CHANNEL_NAME_KEY = "microsoft.channel.name"
CHANNEL_LINK_KEY = "microsoft.channel.link"

# --- Environment variable names ---
ENABLE_A365_OBSERVABILITY_EXPORTER = "ENABLE_A365_OBSERVABILITY_EXPORTER"
A365_OBSERVABILITY_DOMAIN_OVERRIDE = "A365_OBSERVABILITY_DOMAIN_OVERRIDE"
A365_TENANT_ID_ENV = "A365_TENANT_ID"
A365_AGENT_ID_ENV = "A365_AGENT_ID"
A365_CLUSTER_CATEGORY_ENV = "A365_CLUSTER_CATEGORY"
A365_USE_S2S_ENDPOINT_ENV = "A365_USE_S2S_ENDPOINT"
A365_SUPPRESS_INVOKE_AGENT_INPUT_ENV = "A365_SUPPRESS_INVOKE_AGENT_INPUT"

# --- FIC (Federated Identity Credential) token flow env vars ---
A365_AGENT_APP_INSTANCE_ID_ENV = "A365_AGENT_APP_INSTANCE_ID"
A365_AGENTIC_USER_ID_ENV = "A365_AGENTIC_USER_ID"
A365_SERVICE_CLIENT_ID_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID"
A365_SERVICE_CLIENT_SECRET_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET"
A365_SERVICE_TENANT_ID_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID"
