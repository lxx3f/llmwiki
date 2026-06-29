from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from deps import get_scoped_db, get_user_id
from scoped_db import ScopedDB

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    onboarded: bool


@router.get("/v1/me", response_model=MeResponse)
async def get_me(
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
    user_id: Annotated[str, Depends(get_user_id)],
):
    row = await db.fetchrow(
        "SELECT id::text, email, display_name, onboarded FROM users WHERE id = $1",
        user_id,
    )
    if not row:
        return MeResponse(
            id=user_id,
            email="local",
            display_name="Local User",
            onboarded=True,
        )
    return row
