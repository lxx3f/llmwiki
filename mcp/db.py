import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL, min_size=1, max_size=5, command_timeout=15,
        )
    return _pool


async def query(sql: str, *args) -> list[dict]:
    """Execute a query and return all rows as dicts."""
    pool = await get_pool()
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def queryrow(sql: str, *args) -> dict | None:
    """Execute a query and return the first row as a dict, or None."""
    pool = await get_pool()
    row = await pool.fetchrow(sql, *args)
    return dict(row) if row else None


async def execute(sql: str, *args) -> str:
    """Execute a statement."""
    pool = await get_pool()
    return await pool.execute(sql, *args)
