import logging
from os import environ

from aiohttp.web import Application, Request, Response, run_app
from microsoft_agents.hosting.aiohttp import (
    CloudAdapter,
    start_agent_process,
)
from microsoft_agents.hosting.core import AgentApplication, AgentAuthConfiguration
from microsoft_agents_a365.observability.core.config import configure

# from microsoft_agents_a365.observability.hosting.middleware.observability_middleware_registrar import (
#     ObservabilityMiddlewareRegistrar,
# )

from microsoft_agents_a365.observability.hosting.middleware.observability_hosting_manager import (
    ObservabilityHostingManager,
)

from microsoft_agents_a365.observability.hosting.middleware import (
    ObservabilityHostingOptions,
    BaggageMiddleware,
    OutputLoggingMiddleware,
)
from microsoft_agents_a365.observability.hosting.token_cache_helpers import AgenticTokenCache
from utils.payload_logging_exporter import register_guardrail_payload_logging
from utils.sample_exporter_flags import align_exporter_env_flags
from utils.token_cache import get_cached_agentic_token

logger = logging.getLogger(__name__)


def create_token_resolver(token_cache: AgenticTokenCache):
    """
    Factory function that creates a token resolver with injected dependencies.

    Args:
        token_cache: The AgenticTokenCache instance to use for token resolution.

    Returns:
        A token resolver function suitable for Kairo exporter configuration.
    """

    def token_resolver(agent_id: str, tenant_id: str) -> str | None:
        """
        Token resolver function for Kairo exporter.

        Uses the AgenticTokenCache to retrieve observability tokens.
        The cache was registered in the agent's on_message handler with the
        authorization, turn context, and auth handler name.
        """
        try:
            logger.info(f"Token resolver called for agent_id: {agent_id}, tenant_id: {tenant_id}")

            # Use new AgenticTokenCache approach
            import asyncio

            token = asyncio.run(token_cache.get_observability_token(agent_id, tenant_id))

            if token:
                logger.info("Successfully retrieved token from AgenticTokenCache")
                return token.token

            # Fallback: Use cached agentic token from agent authentication (old approach for reference)
            cached_token = get_cached_agentic_token(tenant_id, agent_id)
            if cached_token:
                logger.info("Using cached agentic token from old approach (fallback)")
                return cached_token
            else:
                logger.warning(
                    f"No cached token found for agent_id: {agent_id}, tenant_id: {tenant_id}"
                )
                return None

        except Exception as e:
            logger.error(f"Error resolving token for agent {agent_id}, tenant {tenant_id}: {e}")
            return None

    return token_resolver


def start_server(agent_application: AgentApplication, auth_configuration: AgentAuthConfiguration):
    async def entry_point(req: Request) -> Response:
        agent: AgentApplication = req.app["agent_app"]
        adapter: CloudAdapter = req.app["adapter"]
        return await start_agent_process(
            req,
            agent,
            adapter,
        )

    app = Application()
    app.router.add_post("/api/messages", entry_point)
    app["agent_configuration"] = auth_configuration
    app["agent_app"] = agent_application
    app["adapter"] = agent_application.adapter

    # Create token cache instance and store in app context
    token_cache = AgenticTokenCache()
    app["token_cache"] = token_cache

    # Make token cache available to agent handlers via application storage
    agent_application.adapter.app_context = {"token_cache": token_cache}

    # Prefer the canonical A365 exporter flag and mirror it to the legacy
    # Kairo alias for sample compatibility with older dependencies.
    align_exporter_env_flags(environ)

    # Create token resolver with injected token cache dependency
    token_resolver_func = create_token_resolver(token_cache)

    # Configure Kairo observability with the exporter
    configure(
        service_name="AzureOpenAiKairoTracing",
        service_namespace="AzureOpenAiKairoTesting",
        token_resolver=token_resolver_func,
    )
    register_guardrail_payload_logging()

    ObservabilityHostingManager.configure(
        agent_application.adapter.middleware_set, ObservabilityHostingOptions(True, True)
    )

    # Register observability middleware
    # ObservabilityMiddlewareRegistrar().with_message_logging().apply(agent_application.adapter)

    try:
        run_app(app, host="localhost", port=environ.get("PORT", 3978))
    except Exception as error:
        raise error
