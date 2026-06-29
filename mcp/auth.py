import asyncio
import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

from config import settings

logger = logging.getLogger(__name__)


class SingleUserTokenVerifier(TokenVerifier):
    """Single-user mode: accept any token and return the configured user."""

    async def verify_token(self, token: str) -> AccessToken | None:
        logger.debug("MCP auth: single-user mode (%s)", settings.SINGLE_USER_ID)
        return AccessToken(
            token=token,
            client_id=settings.SINGLE_USER_ID,
            scopes=[],
            extra={"claims": {"sub": settings.SINGLE_USER_ID}},
        )
