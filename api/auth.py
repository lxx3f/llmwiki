from fastapi import Request

from config import settings


async def get_current_user(request: Request) -> str:
    """Single-user mode: return the effective user ID from app state."""
    return request.app.state.effective_user_id
