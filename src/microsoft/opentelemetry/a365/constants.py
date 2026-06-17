# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""Constants for Agent365 observability.

Superset of microsoft-agents-a365-observability-core constants plus
package-specific environment variable constants.

Span operation names:
:var INVOKE_AGENT_OPERATION_NAME: Span operation name for agent invocation.
:vartype INVOKE_AGENT_OPERATION_NAME: str
:var EXECUTE_TOOL_OPERATION_NAME: Span operation name for tool execution.
:vartype EXECUTE_TOOL_OPERATION_NAME: str
:var OUTPUT_MESSAGES_OPERATION_NAME: Span operation name for output message processing.
:vartype OUTPUT_MESSAGES_OPERATION_NAME: str
:var CHAT_OPERATION_NAME: Span operation name for chat requests.
:vartype CHAT_OPERATION_NAME: str
:var APPLY_GUARDRAIL_OPERATION_NAME: Span operation name for guardrail evaluation.
:vartype APPLY_GUARDRAIL_OPERATION_NAME: str

OpenTelemetry semantic conventions:
:var ERROR_TYPE_KEY: Attribute key for error type.
:vartype ERROR_TYPE_KEY: str
:var ERROR_MESSAGE_KEY: Attribute key for error message.
:vartype ERROR_MESSAGE_KEY: str
:var AZ_NAMESPACE_KEY: Attribute key for Azure namespace.
:vartype AZ_NAMESPACE_KEY: str
:var AZURE_RP_NAMESPACE_VALUE: Azure resource provider namespace value.
:vartype AZURE_RP_NAMESPACE_VALUE: str
:var SOURCE_NAME: Source name used for emitted telemetry.
:vartype SOURCE_NAME: str

Feature switches:
:var ENABLE_OPENTELEMETRY_SWITCH: Feature switch for OpenTelemetry enablement.
:vartype ENABLE_OPENTELEMETRY_SWITCH: str
:var TRACE_CONTENTS_SWITCH: Feature switch for GenAI content tracing.
:vartype TRACE_CONTENTS_SWITCH: str
:var TRACE_CONTENTS_ENVIRONMENT_VARIABLE: Env var controlling GenAI content tracing.
:vartype TRACE_CONTENTS_ENVIRONMENT_VARIABLE: str
:var ENABLE_OBSERVABILITY: Env var controlling observability enablement.
:vartype ENABLE_OBSERVABILITY: str
:var ENABLE_A365_OBSERVABILITY: Env var controlling A365 observability enablement.
:vartype ENABLE_A365_OBSERVABILITY: str

GenAI semantic conventions:
:var GEN_AI_CLIENT_OPERATION_DURATION_METRIC_NAME: Metric name for operation duration.
:vartype GEN_AI_CLIENT_OPERATION_DURATION_METRIC_NAME: str
:var GEN_AI_CLIENT_TOKEN_USAGE_METRIC_NAME: Metric name for token usage.
:vartype GEN_AI_CLIENT_TOKEN_USAGE_METRIC_NAME: str
:var GEN_AI_OPERATION_NAME_KEY: Attribute key for operation name.
:vartype GEN_AI_OPERATION_NAME_KEY: str
:var GEN_AI_REQUEST_MAX_TOKENS_KEY: Attribute key for request max tokens.
:vartype GEN_AI_REQUEST_MAX_TOKENS_KEY: str
:var GEN_AI_REQUEST_MODEL_KEY: Attribute key for request model.
:vartype GEN_AI_REQUEST_MODEL_KEY: str
:var GEN_AI_REQUEST_TEMPERATURE_KEY: Attribute key for request temperature.
:vartype GEN_AI_REQUEST_TEMPERATURE_KEY: str
:var GEN_AI_REQUEST_TOP_P_KEY: Attribute key for request top_p.
:vartype GEN_AI_REQUEST_TOP_P_KEY: str
:var GEN_AI_RESPONSE_FINISH_REASONS_KEY: Attribute key for response finish reasons.
:vartype GEN_AI_RESPONSE_FINISH_REASONS_KEY: str
:var GEN_AI_RESPONSE_MODEL_KEY: Attribute key for response model.
:vartype GEN_AI_RESPONSE_MODEL_KEY: str
:var GEN_AI_RESPONSE_ID_KEY: Attribute key for response id.
:vartype GEN_AI_RESPONSE_ID_KEY: str
:var GEN_AI_AGENT_ID_KEY: Attribute key for agent id.
:vartype GEN_AI_AGENT_ID_KEY: str
:var GEN_AI_AGENT_NAME_KEY: Attribute key for agent name.
:vartype GEN_AI_AGENT_NAME_KEY: str
:var GEN_AI_AGENT_DESCRIPTION_KEY: Attribute key for agent description.
:vartype GEN_AI_AGENT_DESCRIPTION_KEY: str
:var GEN_AI_AGENT_VERSION_KEY: Attribute key for agent version.
:vartype GEN_AI_AGENT_VERSION_KEY: str
:var GEN_AI_AGENT_PLATFORM_ID_KEY: Attribute key for platform id.
:vartype GEN_AI_AGENT_PLATFORM_ID_KEY: str
:var GEN_AI_AGENT_THOUGHT_PROCESS_KEY: Attribute key for thought process payload.
:vartype GEN_AI_AGENT_THOUGHT_PROCESS_KEY: str
:var GEN_AI_CONVERSATION_ID_KEY: Attribute key for conversation id.
:vartype GEN_AI_CONVERSATION_ID_KEY: str
:var GEN_AI_CONVERSATION_ITEM_LINK_KEY: Attribute key for conversation item link.
:vartype GEN_AI_CONVERSATION_ITEM_LINK_KEY: str
:var GEN_AI_TOKEN_TYPE_KEY: Attribute key for token type.
:vartype GEN_AI_TOKEN_TYPE_KEY: str
:var GEN_AI_USAGE_INPUT_TOKENS_KEY: Attribute key for input token usage.
:vartype GEN_AI_USAGE_INPUT_TOKENS_KEY: str
:var GEN_AI_USAGE_OUTPUT_TOKENS_KEY: Attribute key for output token usage.
:vartype GEN_AI_USAGE_OUTPUT_TOKENS_KEY: str
:var GEN_AI_CHOICE: Attribute key for model choice metadata.
:vartype GEN_AI_CHOICE: str
:var GEN_AI_PROVIDER_NAME_KEY: Attribute key for provider name.
:vartype GEN_AI_PROVIDER_NAME_KEY: str
:var GEN_AI_SYSTEM_INSTRUCTIONS_KEY: Attribute key for system instructions.
:vartype GEN_AI_SYSTEM_INSTRUCTIONS_KEY: str
:var GEN_AI_INPUT_MESSAGES_KEY: Attribute key for input messages payload.
:vartype GEN_AI_INPUT_MESSAGES_KEY: str
:var GEN_AI_OUTPUT_MESSAGES_KEY: Attribute key for output messages payload.
:vartype GEN_AI_OUTPUT_MESSAGES_KEY: str

Tool execution:
:var GEN_AI_TOOL_CALL_ID_KEY: Attribute key for tool call id.
:vartype GEN_AI_TOOL_CALL_ID_KEY: str
:var GEN_AI_TOOL_NAME_KEY: Attribute key for tool name.
:vartype GEN_AI_TOOL_NAME_KEY: str
:var GEN_AI_TOOL_DESCRIPTION_KEY: Attribute key for tool description.
:vartype GEN_AI_TOOL_DESCRIPTION_KEY: str
:var GEN_AI_TOOL_ARGS_KEY: Attribute key for tool call arguments.
:vartype GEN_AI_TOOL_ARGS_KEY: str
:var GEN_AI_TOOL_CALL_RESULT_KEY: Attribute key for tool call result.
:vartype GEN_AI_TOOL_CALL_RESULT_KEY: str
:var GEN_AI_TOOL_TYPE_KEY: Attribute key for tool type.
:vartype GEN_AI_TOOL_TYPE_KEY: str

Human caller:
:var USER_ID_KEY: Attribute key for human caller id.
:vartype USER_ID_KEY: str
:var USER_NAME_KEY: Attribute key for human caller name.
:vartype USER_NAME_KEY: str
:var USER_EMAIL_KEY: Attribute key for human caller email.
:vartype USER_EMAIL_KEY: str
:var GEN_AI_CALLER_CLIENT_IP_KEY: Attribute key for human caller client IP.
:vartype GEN_AI_CALLER_CLIENT_IP_KEY: str

Agent-to-agent caller:
:var GEN_AI_CALLER_AGENT_USER_ID_KEY: Attribute key for caller agent user id.
:vartype GEN_AI_CALLER_AGENT_USER_ID_KEY: str
:var GEN_AI_CALLER_AGENT_EMAIL_KEY: Attribute key for caller agent user email.
:vartype GEN_AI_CALLER_AGENT_EMAIL_KEY: str
:var GEN_AI_CALLER_AGENT_NAME_KEY: Attribute key for caller agent name.
:vartype GEN_AI_CALLER_AGENT_NAME_KEY: str
:var GEN_AI_CALLER_AGENT_ID_KEY: Attribute key for caller agent id.
:vartype GEN_AI_CALLER_AGENT_ID_KEY: str
:var GEN_AI_CALLER_AGENT_APPLICATION_ID_KEY: Attribute key for caller agent blueprint id.
:vartype GEN_AI_CALLER_AGENT_APPLICATION_ID_KEY: str
:var GEN_AI_CALLER_AGENT_PLATFORM_ID_KEY: Attribute key for caller agent platform id.
:vartype GEN_AI_CALLER_AGENT_PLATFORM_ID_KEY: str
:var GEN_AI_CALLER_AGENT_VERSION_KEY: Attribute key for caller agent version.
:vartype GEN_AI_CALLER_AGENT_VERSION_KEY: str

Agent-specific dimensions:
:var AGENT_ID_KEY: Attribute key for agent id.
:vartype AGENT_ID_KEY: str
:var GEN_AI_TASK_ID_KEY: Attribute key for task id.
:vartype GEN_AI_TASK_ID_KEY: str
:var GEN_AI_ICON_URI_KEY: Attribute key for agent icon URI.
:vartype GEN_AI_ICON_URI_KEY: str
:var GEN_AI_EXECUTION_PAYLOAD_KEY: Attribute key for execution payload.
:vartype GEN_AI_EXECUTION_PAYLOAD_KEY: str
:var TENANT_ID_KEY: Attribute key for tenant id.
:vartype TENANT_ID_KEY: str
:var GEN_AI_AGENT_AUID_KEY: Attribute key for agentic user id.
:vartype GEN_AI_AGENT_AUID_KEY: str
:var GEN_AI_AGENT_EMAIL_KEY: Attribute key for agentic user email.
:vartype GEN_AI_AGENT_EMAIL_KEY: str
:var GEN_AI_AGENT_BLUEPRINT_ID_KEY: Attribute key for agent blueprint id.
:vartype GEN_AI_AGENT_BLUEPRINT_ID_KEY: str
:var SESSION_ID_KEY: Attribute key for session id.
:vartype SESSION_ID_KEY: str
:var SESSION_DESCRIPTION_KEY: Attribute key for session description.
:vartype SESSION_DESCRIPTION_KEY: str

Error types:
:var ERROR_TYPE_CANCELLED: Error type value for cancelled tasks.
:vartype ERROR_TYPE_CANCELLED: str

OTel standard keys:
:var SERVER_ADDRESS_KEY: Attribute key for server address.
:vartype SERVER_ADDRESS_KEY: str
:var SERVER_PORT_KEY: Attribute key for server port.
:vartype SERVER_PORT_KEY: str
:var SERVICE_NAME_KEY: Attribute key for service name.
:vartype SERVICE_NAME_KEY: str

Custom span keys:
:var CUSTOM_PARENT_SPAN_ID_KEY: Attribute key for custom parent span id.
:vartype CUSTOM_PARENT_SPAN_ID_KEY: str
:var CUSTOM_SPAN_NAME_KEY: Attribute key for custom span name.
:vartype CUSTOM_SPAN_NAME_KEY: str

Channel:
:var CHANNEL_NAME_KEY: Attribute key for channel name.
:vartype CHANNEL_NAME_KEY: str
:var CHANNEL_LINK_KEY: Attribute key for channel link.
:vartype CHANNEL_LINK_KEY: str

Guardrail and security:
:var GEN_AI_GUARDIAN_ID_KEY: Attribute key for guardian id.
:vartype GEN_AI_GUARDIAN_ID_KEY: str
:var GEN_AI_GUARDIAN_NAME_KEY: Attribute key for guardian name.
:vartype GEN_AI_GUARDIAN_NAME_KEY: str
:var GEN_AI_GUARDIAN_PROVIDER_NAME_KEY: Attribute key for guardian provider name.
:vartype GEN_AI_GUARDIAN_PROVIDER_NAME_KEY: str
:var GEN_AI_GUARDIAN_VERSION_KEY: Attribute key for guardian version.
:vartype GEN_AI_GUARDIAN_VERSION_KEY: str
:var GEN_AI_SECURITY_DECISION_TYPE_KEY: Attribute key for security decision type.
:vartype GEN_AI_SECURITY_DECISION_TYPE_KEY: str
:var GEN_AI_SECURITY_DECISION_REASON_KEY: Attribute key for security decision reason.
:vartype GEN_AI_SECURITY_DECISION_REASON_KEY: str
:var GEN_AI_SECURITY_DECISION_CODE_KEY: Attribute key for security decision code.
:vartype GEN_AI_SECURITY_DECISION_CODE_KEY: str
:var GEN_AI_SECURITY_TARGET_TYPE_KEY: Attribute key for security target type.
:vartype GEN_AI_SECURITY_TARGET_TYPE_KEY: str
:var GEN_AI_SECURITY_TARGET_ID_KEY: Attribute key for security target id.
:vartype GEN_AI_SECURITY_TARGET_ID_KEY: str
:var GEN_AI_SECURITY_POLICY_ID_KEY: Attribute key for security policy id.
:vartype GEN_AI_SECURITY_POLICY_ID_KEY: str
:var GEN_AI_SECURITY_POLICY_NAME_KEY: Attribute key for security policy name.
:vartype GEN_AI_SECURITY_POLICY_NAME_KEY: str
:var GEN_AI_SECURITY_POLICY_VERSION_KEY: Attribute key for security policy version.
:vartype GEN_AI_SECURITY_POLICY_VERSION_KEY: str
:var GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY: Attribute key for input content hash.
:vartype GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY: str
:var GEN_AI_SECURITY_CONTENT_MODIFIED_KEY: Attribute key for content modified flag.
:vartype GEN_AI_SECURITY_CONTENT_MODIFIED_KEY: str
:var GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY: Attribute key for external event id.
:vartype GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY: str
:var GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY: Attribute key for input content value.
:vartype GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY: str
:var GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY: Attribute key for output content value.
:vartype GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY: str
:var GEN_AI_SECURITY_FINDING_EVENT_NAME: Event name for security findings.
:vartype GEN_AI_SECURITY_FINDING_EVENT_NAME: str
:var GEN_AI_SECURITY_RISK_CATEGORY_KEY: Attribute key for risk category.
:vartype GEN_AI_SECURITY_RISK_CATEGORY_KEY: str
:var GEN_AI_SECURITY_RISK_SEVERITY_KEY: Attribute key for risk severity.
:vartype GEN_AI_SECURITY_RISK_SEVERITY_KEY: str
:var GEN_AI_SECURITY_RISK_SCORE_KEY: Attribute key for risk score.
:vartype GEN_AI_SECURITY_RISK_SCORE_KEY: str
:var GEN_AI_SECURITY_RISK_METADATA_KEY: Attribute key for risk metadata.
:vartype GEN_AI_SECURITY_RISK_METADATA_KEY: str
:var GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY: Attribute key for policy decision type.
:vartype GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY: str

Telemetry SDK attributes:
:var TELEMETRY_SDK_NAME_KEY: Attribute key for telemetry SDK name.
:vartype TELEMETRY_SDK_NAME_KEY: str
:var TELEMETRY_SDK_LANGUAGE_KEY: Attribute key for telemetry SDK language.
:vartype TELEMETRY_SDK_LANGUAGE_KEY: str
:var TELEMETRY_SDK_VERSION_KEY: Attribute key for telemetry SDK version.
:vartype TELEMETRY_SDK_VERSION_KEY: str
:var TELEMETRY_SDK_NAME_VALUE: Telemetry SDK name value.
:vartype TELEMETRY_SDK_NAME_VALUE: str
:var TELEMETRY_SDK_LANGUAGE_VALUE: Telemetry SDK language value.
:vartype TELEMETRY_SDK_LANGUAGE_VALUE: str

Package-specific environment variable names:
:var ENABLE_A365_OBSERVABILITY_EXPORTER: Env var enabling the A365 exporter.
:vartype ENABLE_A365_OBSERVABILITY_EXPORTER: str
:var A365_OBSERVABILITY_DOMAIN_OVERRIDE: Env var overriding the A365 domain.
:vartype A365_OBSERVABILITY_DOMAIN_OVERRIDE: str
:var A365_TENANT_ID_ENV: Env var for tenant id.
:vartype A365_TENANT_ID_ENV: str
:var A365_AGENT_ID_ENV: Env var for agent id.
:vartype A365_AGENT_ID_ENV: str
:var A365_CLUSTER_CATEGORY_ENV: Env var for cluster category.
:vartype A365_CLUSTER_CATEGORY_ENV: str
:var A365_USE_S2S_ENDPOINT_ENV: Env var toggling S2S endpoint usage.
:vartype A365_USE_S2S_ENDPOINT_ENV: str
:var A365_SUPPRESS_INVOKE_AGENT_INPUT_ENV: Env var suppressing invoke input capture.
:vartype A365_SUPPRESS_INVOKE_AGENT_INPUT_ENV: str
:var A365_OBSERVABILITY_SCOPE_OVERRIDE_ENV: Env var overriding observability scope.
:vartype A365_OBSERVABILITY_SCOPE_OVERRIDE_ENV: str

HTTP timeout:
:var A365_HTTP_TIMEOUT_SECONDS: HTTP timeout in seconds for outbound calls.
:vartype A365_HTTP_TIMEOUT_SECONDS: float

FIC token flow environment variables:
:var A365_AGENT_APP_INSTANCE_ID_ENV: Env var for agent app instance id.
:vartype A365_AGENT_APP_INSTANCE_ID_ENV: str
:var A365_AGENTIC_USER_ID_ENV: Env var for agentic user id.
:vartype A365_AGENTIC_USER_ID_ENV: str
:var A365_SERVICE_CLIENT_ID_ENV: Env var for service connection client id.
:vartype A365_SERVICE_CLIENT_ID_ENV: str
:var A365_SERVICE_CLIENT_SECRET_ENV: Env var for service connection client secret.
:vartype A365_SERVICE_CLIENT_SECRET_ENV: str
:var A365_SERVICE_TENANT_ID_ENV: Env var for service connection tenant id.
:vartype A365_SERVICE_TENANT_ID_ENV: str
"""

# --- Span operation names ---
INVOKE_AGENT_OPERATION_NAME = "invoke_agent"
EXECUTE_TOOL_OPERATION_NAME = "execute_tool"
OUTPUT_MESSAGES_OPERATION_NAME = "output_messages"
CHAT_OPERATION_NAME = "chat"
APPLY_GUARDRAIL_OPERATION_NAME = "apply_guardrail"

# --- OpenTelemetry semantic conventions ---
ERROR_TYPE_KEY = "error.type"
ERROR_MESSAGE_KEY = "error.message"
AZ_NAMESPACE_KEY = "az.namespace"
AZURE_RP_NAMESPACE_VALUE = "Microsoft.CognitiveServices"
SOURCE_NAME = "Agent365Sdk"

# --- Feature switches ---
ENABLE_OPENTELEMETRY_SWITCH = "Azure.Experimental.EnableActivitySource"
TRACE_CONTENTS_SWITCH = "Azure.Experimental.TraceGenAIMessageContent"
TRACE_CONTENTS_ENVIRONMENT_VARIABLE = "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"
ENABLE_OBSERVABILITY = "ENABLE_OBSERVABILITY"
ENABLE_A365_OBSERVABILITY = "ENABLE_A365_OBSERVABILITY"

# --- GenAI semantic conventions ---
GEN_AI_CLIENT_OPERATION_DURATION_METRIC_NAME = "gen_ai.client.operation.duration"
GEN_AI_CLIENT_TOKEN_USAGE_METRIC_NAME = "gen_ai.client.token.usage"
GEN_AI_OPERATION_NAME_KEY = "gen_ai.operation.name"
GEN_AI_REQUEST_MAX_TOKENS_KEY = "gen_ai.request.max_tokens"
GEN_AI_REQUEST_MODEL_KEY = "gen_ai.request.model"
GEN_AI_REQUEST_TEMPERATURE_KEY = "gen_ai.request.temperature"
GEN_AI_REQUEST_TOP_P_KEY = "gen_ai.request.top_p"
GEN_AI_RESPONSE_FINISH_REASONS_KEY = "gen_ai.response.finish_reasons"
GEN_AI_RESPONSE_MODEL_KEY = "gen_ai.response.model"
GEN_AI_RESPONSE_ID_KEY = "gen_ai.response.id"
GEN_AI_AGENT_ID_KEY = "gen_ai.agent.id"
GEN_AI_AGENT_NAME_KEY = "gen_ai.agent.name"
GEN_AI_AGENT_DESCRIPTION_KEY = "gen_ai.agent.description"
GEN_AI_AGENT_VERSION_KEY = "gen_ai.agent.version"
GEN_AI_AGENT_PLATFORM_ID_KEY = "microsoft.a365.agent.platform.id"
GEN_AI_AGENT_THOUGHT_PROCESS_KEY = "microsoft.a365.agent.thought.process"
GEN_AI_CONVERSATION_ID_KEY = "gen_ai.conversation.id"
GEN_AI_CONVERSATION_ITEM_LINK_KEY = "microsoft.conversation.item.link"
GEN_AI_TOKEN_TYPE_KEY = "gen_ai.token.type"
GEN_AI_USAGE_INPUT_TOKENS_KEY = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS_KEY = "gen_ai.usage.output_tokens"
GEN_AI_CHOICE = "gen_ai.choice"
GEN_AI_PROVIDER_NAME_KEY = "gen_ai.provider.name"
GEN_AI_SYSTEM_INSTRUCTIONS_KEY = "gen_ai.system_instructions"
GEN_AI_INPUT_MESSAGES_KEY = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES_KEY = "gen_ai.output.messages"

# --- Tool execution ---
GEN_AI_TOOL_CALL_ID_KEY = "gen_ai.tool.call.id"
GEN_AI_TOOL_NAME_KEY = "gen_ai.tool.name"
GEN_AI_TOOL_DESCRIPTION_KEY = "gen_ai.tool.description"
GEN_AI_TOOL_ARGS_KEY = "gen_ai.tool.call.arguments"
GEN_AI_TOOL_CALL_RESULT_KEY = "gen_ai.tool.call.result"
GEN_AI_TOOL_TYPE_KEY = "gen_ai.tool.type"

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

# --- Agent-specific dimensions ---
AGENT_ID_KEY = "gen_ai.agent.id"
GEN_AI_TASK_ID_KEY = "gen_ai.task.id"
GEN_AI_ICON_URI_KEY = "gen_ai.agent365.icon_uri"
GEN_AI_EXECUTION_PAYLOAD_KEY = "gen_ai.execution.payload"
TENANT_ID_KEY = "microsoft.tenant.id"
GEN_AI_AGENT_AUID_KEY = "microsoft.agent.user.id"
GEN_AI_AGENT_EMAIL_KEY = "microsoft.agent.user.email"
GEN_AI_AGENT_BLUEPRINT_ID_KEY = "microsoft.a365.agent.blueprint.id"
SESSION_ID_KEY = "microsoft.session.id"
SESSION_DESCRIPTION_KEY = "microsoft.session.description"

# --- Error type constants ---
ERROR_TYPE_CANCELLED = "TaskCanceledException"

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

# --- Guardrail / Security ---
GEN_AI_GUARDIAN_ID_KEY = "microsoft.guardian.id"
GEN_AI_GUARDIAN_NAME_KEY = "microsoft.guardian.name"
GEN_AI_GUARDIAN_PROVIDER_NAME_KEY = "microsoft.guardian.provider.name"
GEN_AI_GUARDIAN_VERSION_KEY = "microsoft.guardian.version"
GEN_AI_SECURITY_DECISION_TYPE_KEY = "microsoft.security.decision.type"
GEN_AI_SECURITY_DECISION_REASON_KEY = "microsoft.security.decision.reason"
GEN_AI_SECURITY_DECISION_CODE_KEY = "microsoft.security.decision.code"
GEN_AI_SECURITY_TARGET_TYPE_KEY = "microsoft.security.target.type"
GEN_AI_SECURITY_TARGET_ID_KEY = "microsoft.security.target.id"
GEN_AI_SECURITY_POLICY_ID_KEY = "microsoft.security.policy.id"
GEN_AI_SECURITY_POLICY_NAME_KEY = "microsoft.security.policy.name"
GEN_AI_SECURITY_POLICY_VERSION_KEY = "microsoft.security.policy.version"
GEN_AI_SECURITY_CONTENT_INPUT_HASH_KEY = "microsoft.security.content.input.hash"
GEN_AI_SECURITY_CONTENT_MODIFIED_KEY = "microsoft.security.content.modified"
GEN_AI_SECURITY_EXTERNAL_EVENT_ID_KEY = "microsoft.security.external_event_id"
GEN_AI_SECURITY_CONTENT_INPUT_VALUE_KEY = "microsoft.security.content.input.value"
GEN_AI_SECURITY_CONTENT_OUTPUT_VALUE_KEY = "microsoft.security.content.output.value"
GEN_AI_SECURITY_FINDING_EVENT_NAME = "microsoft.security.finding"
GEN_AI_SECURITY_RISK_CATEGORY_KEY = "microsoft.security.risk.category"
GEN_AI_SECURITY_RISK_SEVERITY_KEY = "microsoft.security.risk.severity"
GEN_AI_SECURITY_RISK_SCORE_KEY = "microsoft.security.risk.score"
GEN_AI_SECURITY_RISK_METADATA_KEY = "microsoft.security.risk.metadata"
GEN_AI_SECURITY_POLICY_DECISION_TYPE_KEY = "microsoft.security.policy.decision.type"

# --- Telemetry SDK attributes ---
TELEMETRY_SDK_NAME_KEY = "telemetry.sdk.name"
TELEMETRY_SDK_LANGUAGE_KEY = "telemetry.sdk.language"
TELEMETRY_SDK_VERSION_KEY = "telemetry.sdk.version"
TELEMETRY_SDK_NAME_VALUE = "microsoft-opentelemetry"
TELEMETRY_SDK_LANGUAGE_VALUE = "python"

# --- Package-specific environment variable names ---
ENABLE_A365_OBSERVABILITY_EXPORTER = "ENABLE_A365_OBSERVABILITY_EXPORTER"
A365_OBSERVABILITY_DOMAIN_OVERRIDE = "A365_OBSERVABILITY_DOMAIN_OVERRIDE"
A365_TENANT_ID_ENV = "A365_TENANT_ID"
A365_AGENT_ID_ENV = "A365_AGENT_ID"
A365_CLUSTER_CATEGORY_ENV = "A365_CLUSTER_CATEGORY"
A365_USE_S2S_ENDPOINT_ENV = "A365_USE_S2S_ENDPOINT"
A365_SUPPRESS_INVOKE_AGENT_INPUT_ENV = "A365_SUPPRESS_INVOKE_AGENT_INPUT"
A365_OBSERVABILITY_SCOPE_OVERRIDE_ENV = "A365_OBSERVABILITY_SCOPE_OVERRIDE"

# --- HTTP timeout (seconds) for outbound calls (token acquisition & export) ---
A365_HTTP_TIMEOUT_SECONDS: float = 30.0

# --- FIC (Federated Identity Credential) token flow env vars ---
A365_AGENT_APP_INSTANCE_ID_ENV = "A365_AGENT_APP_INSTANCE_ID"
A365_AGENTIC_USER_ID_ENV = "A365_AGENTIC_USER_ID"
A365_SERVICE_CLIENT_ID_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID"
A365_SERVICE_CLIENT_SECRET_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET"
A365_SERVICE_TENANT_ID_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID"
