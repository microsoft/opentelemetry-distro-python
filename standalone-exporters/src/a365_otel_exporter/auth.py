"""Token resolver utilities for A365 SpanExporter authentication."""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Type alias for token resolver functions.
# A token resolver receives (agent_id, tenant_id) and returns a bearer token
# string, or None if a token could not be obtained.
TokenResolver = Callable[[str, str], Optional[str]]

# Default scope for the Agent 365 production first-party application.
_DEFAULT_SCOPE = "9b975845-388f-4429-889e-eab1ef63949c/.default"


def create_azure_identity_resolver(
    credential: object = None,
    scopes: Optional[list[str]] = None,
) -> TokenResolver:
    """Create a token resolver backed by ``azure.identity``.

    Parameters
    ----------
    credential:
        An ``azure.identity`` credential instance (e.g.
        ``DefaultAzureCredential``).  When *None*, a new
        ``DefaultAzureCredential`` is created on first call.
    scopes:
        OAuth scopes to request.  Defaults to the A365 production app scope.

    Returns
    -------
    TokenResolver
        A synchronous function ``(agent_id, tenant_id) -> Optional[str]``.

    Raises
    ------
    ImportError
        If ``azure-identity`` is not installed.  Install the package with::

            pip install a365-otel-exporter[azure]
    """
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "azure-identity is required for create_azure_identity_resolver. "
            "Install it with: pip install a365-otel-exporter[azure]"
        )

    resolved_scopes = scopes or [_DEFAULT_SCOPE]
    resolved_credential = credential

    def _resolve(agent_id: str, tenant_id: str) -> Optional[str]:
        nonlocal resolved_credential
        if resolved_credential is None:
            resolved_credential = DefaultAzureCredential()
        try:
            token = resolved_credential.get_token(*resolved_scopes)
            return token.token
        except Exception:
            logger.warning(
                "Failed to acquire token via azure-identity for "
                "agent_id=%s tenant_id=%s",
                agent_id,
                tenant_id,
                exc_info=True,
            )
            return None

    return _resolve


def create_msal_resolver(
    client_id: str,
    client_secret: str,
    tenant_id: str,
    authority: Optional[str] = None,
    scopes: Optional[list[str]] = None,
) -> TokenResolver:
    """Create a token resolver backed by MSAL confidential client credentials.

    Parameters
    ----------
    client_id:
        Azure AD application (client) ID.
    client_secret:
        Client secret for the application.
    tenant_id:
        Azure AD tenant ID for the confidential client.
    authority:
        Authority URL.  Defaults to
        ``https://login.microsoftonline.com/{tenant_id}``.
    scopes:
        OAuth scopes to request.  Defaults to the A365 production app scope.

    Returns
    -------
    TokenResolver
        A synchronous function ``(agent_id, tenant_id) -> Optional[str]``.

    Raises
    ------
    ImportError
        If ``msal`` is not installed.  Install the package with::

            pip install a365-otel-exporter[msal]
    """
    try:
        import msal  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "msal is required for create_msal_resolver. "
            "Install it with: pip install a365-otel-exporter[msal]"
        )

    resolved_authority = authority or f"https://login.microsoftonline.com/{tenant_id}"
    resolved_scopes = scopes or [_DEFAULT_SCOPE]

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=resolved_authority,
    )

    def _resolve(agent_id: str, _tenant_id: str) -> Optional[str]:
        try:
            result = app.acquire_token_for_client(scopes=resolved_scopes)
            if result and "access_token" in result:
                return result["access_token"]
            error_desc = result.get("error_description", "unknown error") if result else "no result"
            logger.warning(
                "MSAL token acquisition failed for agent_id=%s tenant_id=%s: %s",
                agent_id,
                _tenant_id,
                error_desc,
            )
            return None
        except Exception:
            logger.warning(
                "Failed to acquire token via MSAL for agent_id=%s tenant_id=%s",
                agent_id,
                _tenant_id,
                exc_info=True,
            )
            return None

    return _resolve
