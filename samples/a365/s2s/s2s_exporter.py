# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Sample: A365 Exporter with S2S (Service-to-Service) authentication

Demonstrates how to export A365 telemetry using the **S2S endpoint** with a
service-principal (app registration) token resolver. Unlike the AI-teammate
flow, the S2S scenario has **no agentic user** — a service authenticates on
its own behalf using its client credentials and exports telemetry for the
agents it operates.

Two things make this an S2S sample:
  1. ``a365_use_s2s_endpoint=True`` — routes export to the S2S ingest path.
  2. A custom ``a365_token_resolver`` that performs the MSAL app -> instance
     token exchange and acquires an *application* token for the A365
     observability scope. No user context is involved.

The telemetry itself is produced with the A365 scope classes (manual
instrumentation), so the sample is self-contained and needs no LLM.

The token resolver mirrors the SDK's FIC flow (``_create_fic_token_resolver``
in ``a365/core/exporters/utils.py``): a two-step app -> instance token
exchange via MSAL, then an *application* token for the A365 observability
scope. The agentic-user step (``A365_AGENTIC_USER_ID`` / ``user_fic`` grant)
is intentionally excluded because this is the S2S scenario.

Environment variables:
  ENABLE_OBSERVABILITY=true                     Required to enable scope telemetry
  ENABLE_A365_OBSERVABILITY_EXPORTER=true       Enable A365 HTTP exporter
  CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=<blueprint-app-client-id>
  CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET=<blueprint-app-secret>
  CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=<tenant-guid>
  A365_AGENT_APP_INSTANCE_ID=<agent-app-instance-id>
  A365_AGENT_BLUEPRINT_ID=<agent-blueprint-id>
  A365_CALLER_USER_ID=<caller-user-id>
  A365_CALLER_USER_EMAIL=<caller-user-email>
  A365_CALLER_CLIENT_IP=<caller-client-ip>

The tenant ID and agent ID also populate ``AgentDetails`` and drive the export
URL, so they must match an onboarded agent for the endpoint to accept telemetry.

The app registration must be granted the ``Agent365.Observability.OtelWrite``
**application** permission (with admin consent). See MIGRATION_A365.md ->
"Troubleshooting — Permissions and Setup".
"""

import logging
import os
import threading
import time
from typing import Optional

from microsoft.opentelemetry import use_microsoft_opentelemetry
from microsoft.opentelemetry.a365.core import (
    AgentDetails,
    ApplyGuardrailScope,
    BaggageBuilder,
    CallerDetails,
    Channel,
    ChatMessage,
    ExecuteToolScope,
    GuardrailDecisionType,
    GuardrailDetails,
    GuardrailFinding,
    GuardrailRiskSeverity,
    GuardrailTargetType,
    InferenceCallDetails,
    InferenceOperationType,
    InferenceScope,
    InputMessages,
    InvokeAgentScope,
    InvokeAgentScopeDetails,
    MessageRole,
    OutputScope,
    OutputMessage,
    OutputMessages,
    Request,
    Response,
    ServiceEndpoint,
    SpanDetails,
    TextPart,
    ToolCallDetails,
    ToolType,
    UserDetails,
)

# The A365 observability scope. For the S2S (app-only) client-credential flow,
# Azure AD requires the resource's ``/.default`` scope rather than a specific
# delegated scope like ``Agent365.Observability.OtelWrite`` (which is only valid
# in the FIC ``user_fic`` grant used by the AI-teammate flow).
A365_OBSERVABILITY_SCOPE = "api://9b975845-388f-4429-889e-eab1ef63949c/.default"

# FIC token-flow environment variable names (mirrors the SDK constants).
A365_SERVICE_CLIENT_ID_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID"
A365_SERVICE_CLIENT_SECRET_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET"
A365_SERVICE_TENANT_ID_ENV = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID"
A365_AGENT_APP_INSTANCE_ID_ENV = "A365_AGENT_APP_INSTANCE_ID"
A365_AGENT_BLUEPRINT_ID_ENV = "A365_AGENT_BLUEPRINT_ID"
A365_CALLER_USER_ID_ENV = "A365_CALLER_USER_ID"
A365_CALLER_USER_EMAIL_ENV = "A365_CALLER_USER_EMAIL"
A365_CALLER_CLIENT_IP_ENV = "A365_CALLER_CLIENT_IP"


def _require_env(name: str) -> str:
    """Read a required env var, rejecting empty or unfilled ``<...>`` placeholders."""
    value = os.environ.get(name, "").strip()
    if not value or (value.startswith("<") and value.endswith(">")):
        raise SystemExit(
            f"Environment variable {name} is not set. Set the required shell variables "
            "and run the sample as described in samples/a365/s2s/README.md."
        )
    return value


def build_s2s_token_resolver():
    """Build an S2S token resolver mirroring the SDK's FIC flow, minus the user.

    Performs the same two-step app -> instance token exchange via MSAL as
    ``_create_fic_token_resolver``, then acquires an *application* token for the
    A365 observability scope. The agentic-user step (``A365_AGENTIC_USER_ID`` /
    ``user_fic`` grant) is excluded because the service authenticates on its own
    behalf in the S2S scenario.

    Returns a ``(agent_id, tenant_id) -> token | None`` callable. Tokens are
    cached per ``tenant:agent`` with a 60 s refresh buffer.

    Required environment variables:
      - ``CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID``
      - ``CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET``
      - ``CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID``
      - ``A365_AGENT_APP_INSTANCE_ID``
    """
    try:
        import msal
    except ImportError as exc:
        raise SystemExit(
            "msal is required for the S2S sample. Run `uv run --with msal python "
            "samples/a365/s2s/s2s_exporter.py` from the repository root as described "
            "in samples/a365/s2s/README.md."
        ) from exc

    client_id = _require_env(A365_SERVICE_CLIENT_ID_ENV)
    client_secret = _require_env(A365_SERVICE_CLIENT_SECRET_ENV)
    configured_tenant_id = _require_env(A365_SERVICE_TENANT_ID_ENV)
    instance_id = _require_env(A365_AGENT_APP_INSTANCE_ID_ENV)

    cache: dict[str, tuple[str, float]] = {}
    lock = threading.Lock()

    def resolve(agent_id: str, request_tenant_id: str) -> Optional[str]:  # pylint: disable=too-many-return-statements
        # The resolver runs on the exporter's worker thread; guard the cache to
        # keep token acquisition thread-safe.
        cache_key = f"{request_tenant_id}:{agent_id}"

        # Authenticate against the tenant the telemetry is being exported for, so
        # the token audience matches the cache key. Fail fast if the request's
        # tenant diverges from the configured credentials, since acquiring a token
        # for a different tenant than we cache under yields confusing failures.
        if request_tenant_id != configured_tenant_id:
            print(
                f"S2S token acquisition failed: request tenant {request_tenant_id!r} "
                f"does not match configured tenant {configured_tenant_id!r}."
            )
            return None
        if agent_id != instance_id:
            print(
                f"S2S token acquisition failed: request agent {agent_id!r} "
                f"does not match configured agent instance {instance_id!r}."
            )
            return None
        authority = f"https://login.microsoftonline.com/{request_tenant_id}"

        with lock:
            cached = cache.get(cache_key)
            if cached is not None:
                token, expires_at = cached
                if time.time() < expires_at - 60:  # 60 s buffer
                    return token

        try:
            # Step 1: Agent application token via fmi_path.
            app = msal.ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=authority,
            )
            result = app.acquire_token_for_client(
                scopes=["api://AzureAdTokenExchange/.default"],
                fmi_path=instance_id,
            )
            if "access_token" not in result:
                print(f"S2S step 1 (app token) failed: {result.get('error_description', result)}")
                return None
            agent_token = result["access_token"]

            # Step 2: Instance app authenticated with the agent token as a
            # client assertion. (No agentic-user / user_fic step in S2S.)
            # Pass the assertion as a no-arg callable (MSAL's recommended form)
            # so it can be re-read on demand instead of as a static string.
            instance_app = msal.ConfidentialClientApplication(
                client_id=instance_id,
                client_credential={"client_assertion": lambda: agent_token},
                authority=authority,
            )

            # Step 3: Application token for the A365 observability scope.
            result = instance_app.acquire_token_for_client(
                scopes=[A365_OBSERVABILITY_SCOPE],
            )
            if "access_token" not in result:
                print("S2S step 3 (observability token) failed: " f"{result.get('error_description', result)}")
                return None

            access_token = result["access_token"]
            expires_in = result.get("expires_in", 3600)

            with lock:
                cache[cache_key] = (access_token, time.time() + expires_in)
            return access_token

        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"S2S token acquisition failed: {exc}")
            return None

    return resolve


def _configure_export_logging() -> None:
    """Surface the A365 exporter's logs so the developer can see the export result.

    The exporter logs the HTTP status and correlation id at DEBUG level, e.g.
    ``HTTP 200 success on attempt 1. Correlation ID: <id>. Response: ...`` on
    success, or an error log on failure. Without this, those messages are
    suppressed and the run looks identical whether or not export succeeded.
    """
    exporter_logger = logging.getLogger("microsoft.opentelemetry.a365.core.exporters.agent365_exporter")
    exporter_logger.setLevel(logging.DEBUG)
    # Disable propagation so records aren't also emitted via the root logger,
    # and only attach our handler once so repeated runs in the same process
    # (interactive sessions / test harnesses) don't duplicate log output.
    exporter_logger.propagate = False
    handler_name = "a365-s2s-sample-export-logging"
    if any(getattr(h, "name", None) == handler_name for h in exporter_logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.name = handler_name
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    exporter_logger.addHandler(handler)


def _emit_sample_telemetry(
    agent_details: AgentDetails,
    user_details: UserDetails,
    request: Request,
) -> str:
    """Emit deterministic Store-validation telemetry without network calls."""
    user_question = request.content
    if not isinstance(user_question, str):
        raise ValueError("The S2S sample request content must be a string.")
    final_answer = "It's currently 62°F and partly cloudy in Seattle."
    invoke_context = None
    baggage = (
        BaggageBuilder()
        .tenant_id(agent_details.tenant_id)
        .agent_id(agent_details.agent_id)
        .agent_blueprint_id(agent_details.agent_blueprint_id)
        .agent_name(agent_details.agent_name)
        .agent_description(agent_details.agent_description)
        .agent_version(agent_details.agent_version)
        .user_id(user_details.user_id)
        .user_email(user_details.user_email)
        .user_name(user_details.user_name)
        .user_client_ip(user_details.user_client_ip)
        .channel_name(request.channel.name if request.channel else None)
        .channel_links(request.channel.link if request.channel else None)
        .session_id(request.session_id)
        .conversation_id(request.conversation_id)
        .invoke_agent_server("weather-agent.contoso.com", 8443)
    )

    with baggage.build():
        with InvokeAgentScope.start(
            request=request,
            scope_details=InvokeAgentScopeDetails(
                endpoint=ServiceEndpoint(hostname="weather-agent.contoso.com", port=8443),
            ),
            agent_details=agent_details,
            caller_details=CallerDetails(user_details=user_details),
        ) as invoke_scope:
            invoke_scope.record_input_messages(
                InputMessages(
                    messages=[
                        ChatMessage(
                            role=MessageRole.USER,
                            parts=[TextPart(content=user_question)],
                        ),
                    ]
                )
            )

            with ApplyGuardrailScope.start(
                details=GuardrailDetails(
                    target_type=GuardrailTargetType.LLM_INPUT,
                    decision_type=GuardrailDecisionType.ALLOW,
                    guardian_name="Sample Content Safety",
                    guardian_id="sample-content-safety",
                    guardian_provider_name="contoso.security",
                    guardian_version="1.0",
                    target_id="prompt-123",
                    decision_reason="No unsafe content detected",
                    decision_code="allowed",
                    policy_id="policy-123",
                    policy_name="Default Prompt Safety",
                    policy_version="1.0",
                    content_modified=False,
                ),
                agent_details=agent_details,
                request=request,
                user_details=user_details,
            ) as guardrail_scope:
                guardrail_scope.record_content_input(user_question)
                guardrail_scope.record_finding(
                    GuardrailFinding(
                        risk_category="unsafe_content",
                        risk_severity=GuardrailRiskSeverity.NONE,
                        risk_score=0.0,
                        policy_decision_type=GuardrailDecisionType.ALLOW,
                        policy_id="policy-123",
                        policy_name="Default Prompt Safety",
                        policy_version="1.0",
                    )
                )

            with InferenceScope.start(
                request=request,
                details=InferenceCallDetails(
                    operationName=InferenceOperationType.CHAT,
                    model="gpt-4o",
                    providerName="azure-openai",
                    endpoint=ServiceEndpoint(hostname="example.openai.azure.com", port=443),
                ),
                agent_details=agent_details,
                user_details=user_details,
            ) as inference_scope:
                inference_scope.record_input_messages(
                    InputMessages(
                        messages=[
                            ChatMessage(
                                role=MessageRole.SYSTEM,
                                parts=[TextPart(content="You are a helpful weather assistant.")],
                            ),
                            ChatMessage(
                                role=MessageRole.USER,
                                parts=[TextPart(content=user_question)],
                            ),
                        ]
                    )
                )
                inference_scope.record_input_tokens(45)
                inference_scope.record_output_tokens(12)
                inference_scope.record_finish_reasons(["tool_call"])
                inference_scope.record_output_messages(
                    OutputMessages(
                        messages=[
                            OutputMessage(
                                role=MessageRole.ASSISTANT,
                                parts=[TextPart(content="I'll look up the weather for Seattle.")],
                                finish_reason="tool_call",
                            ),
                        ]
                    )
                )

            with ExecuteToolScope.start(
                request=request,
                details=ToolCallDetails(
                    tool_name="get_weather",
                    arguments={"city": "Seattle", "units": "fahrenheit"},
                    tool_call_id="call-123",
                    description="Fetches current weather for a city",
                    tool_type=ToolType.FUNCTION.value,
                    endpoint=ServiceEndpoint(hostname="weather-api.contoso.com", port=443),
                ),
                agent_details=agent_details,
                user_details=user_details,
            ) as tool_scope:
                tool_scope.record_response('{"temperature":62,"condition":"Partly cloudy"}')

            invoke_scope.record_output_messages(
                OutputMessages(
                    messages=[
                        OutputMessage(
                            role=MessageRole.ASSISTANT,
                            parts=[TextPart(content=final_answer)],
                            finish_reason="stop",
                        ),
                    ]
                )
            )
            invoke_context = invoke_scope.get_context()

        assert invoke_context is not None
        with OutputScope.start(
            request=request,
            response=Response(messages=final_answer),
            agent_details=agent_details,
            user_details=user_details,
            span_details=SpanDetails(parent_context=invoke_context),
        ) as output_scope:
            if request.channel:
                output_scope.set_tag_maybe("microsoft.channel.name", request.channel.name)

    return final_answer


def main():
    _configure_export_logging()
    use_microsoft_opentelemetry(
        enable_a365=True,
        a365_use_s2s_endpoint=True,
        a365_token_resolver=build_s2s_token_resolver(),
    )
    print("Telemetry configured for S2S export.\n")

    agent = AgentDetails(
        agent_id=_require_env(A365_AGENT_APP_INSTANCE_ID_ENV),
        agent_name="Weather Agent",
        agent_description="Answers weather-related questions",
        agent_blueprint_id=_require_env(A365_AGENT_BLUEPRINT_ID_ENV),
        tenant_id=_require_env(A365_SERVICE_TENANT_ID_ENV),
        provider_name="azure-openai",
        agent_version="1.0.0",
    )
    user = UserDetails(
        user_id=_require_env(A365_CALLER_USER_ID_ENV),
        user_email=_require_env(A365_CALLER_USER_EMAIL_ENV),
        user_name="Sample Caller",
        user_client_ip=_require_env(A365_CALLER_CLIENT_IP_ENV),
    )
    request = Request(
        content="What's the weather in Seattle?",
        session_id="session-s2s-123",
        channel=Channel(name="service", link="https://contoso.example/a365-s2s"),
        conversation_id="conv-s2s-789",
    )
    _emit_sample_telemetry(agent, user, request)

    print(
        "\nDone. All spans have been recorded. They are flushed to the A365 "
        "batch span processor and exported on shutdown when "
        "ENABLE_A365_OBSERVABILITY_EXPORTER=true."
    )


if __name__ == "__main__":
    main()
