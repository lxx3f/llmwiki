from typing import Annotated, AsyncGenerator

import asyncpg
from fastapi import Depends, Request

from auth import get_current_user
from config import settings
from scoped_db import ScopedDB


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


async def get_user_id(request: Request) -> str:
    """Single-user mode: return the effective user ID from app state."""
    return request.app.state.effective_user_id


async def get_scoped_db(
    request: Request,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AsyncGenerator[ScopedDB, None]:
    """Simplified scoped DB — connection management only, no RLS."""
    user_id = request.app.state.effective_user_id
    conn = await pool.acquire()
    tr = conn.transaction()
    await tr.start()
    try:
        yield ScopedDB(pool, conn, user_id)
        await tr.commit()
    except Exception:
        await tr.rollback()
        raise
    finally:
        await pool.release(conn)
