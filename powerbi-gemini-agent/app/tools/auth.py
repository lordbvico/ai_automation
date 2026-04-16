"""Azure Active Directory authentication for the Power BI REST API.

Uses MSAL ConfidentialClientApplication with the client-credentials (service-principal)
flow so the agent can run unattended without user interaction.

Required environment variables
--------------------------------
AZURE_TENANT_ID     : Azure AD tenant ID
AZURE_CLIENT_ID     : Service-principal application (client) ID
AZURE_CLIENT_SECRET : Service-principal client secret

These are injected at runtime from GCP Secret Manager — never hard-coded.
"""

from __future__ import annotations

import logging
import os
import time
from threading import Lock

import msal

logger = logging.getLogger(__name__)

_POWERBI_SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

# Module-level token cache — shared across all tool calls in the same process.
# MSAL handles silent refresh automatically via the in-memory token cache.
_app: msal.ConfidentialClientApplication | None = None
_app_lock = Lock()

# Simple in-process cache: (token_str, expiry_epoch)
_token_cache: tuple[str, float] | None = None
_token_lock = Lock()


def _get_msal_app() -> msal.ConfidentialClientApplication:
    """Return a cached MSAL app, creating it on first call."""
    global _app
    with _app_lock:
        if _app is None:
            tenant_id = os.environ["AZURE_TENANT_ID"]
            client_id = os.environ["AZURE_CLIENT_ID"]
            client_secret = os.environ["AZURE_CLIENT_SECRET"]

            authority = f"https://login.microsoftonline.com/{tenant_id}"
            _app = msal.ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=authority,
                # MSAL in-memory token cache — handles silent refresh automatically.
                token_cache=msal.SerializableTokenCache(),
            )
            logger.info("MSAL ConfidentialClientApplication initialised (tenant=%s)", tenant_id)
    return _app


def get_access_token() -> str:
    """Return a valid Power BI bearer token, refreshing silently when needed.

    Raises:
        RuntimeError: If MSAL cannot acquire a token (e.g. wrong credentials).
        KeyError: If required environment variables are missing.
    """
    global _token_cache

    with _token_lock:
        # Return cached token if it expires more than 60 s in the future.
        if _token_cache is not None:
            token_str, expiry = _token_cache
            if time.time() < expiry - 60:
                return token_str

        app = _get_msal_app()

        # Try silent first (uses MSAL's internal cache / refresh token).
        result = app.acquire_token_silent(_POWERBI_SCOPE, account=None)

        if not result:
            # Fall back to client-credentials grant.
            result = app.acquire_token_for_client(scopes=_POWERBI_SCOPE)

        if "access_token" not in result:
            error = result.get("error", "unknown")
            desc = result.get("error_description", "")
            raise RuntimeError(
                f"Failed to acquire Power BI token: {error} — {desc}"
            )

        token_str = result["access_token"]
        # MSAL reports expires_in in seconds from now.
        expires_in = result.get("expires_in", 3600)
        _token_cache = (token_str, time.time() + expires_in)
        logger.info("Acquired new Power BI token (expires_in=%ds)", expires_in)
        return token_str


def get_auth_headers() -> dict[str, str]:
    """Return HTTP headers containing a valid Bearer token."""
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }
