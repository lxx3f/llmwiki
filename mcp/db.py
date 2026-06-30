import logging
import asyncpg

from config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_DB_CONNECT_HELP = (
    "❌ 无法连接到 PostgreSQL 数据库，请检查：\n"
    "  1. Docker 容器是否已启动？运行: docker compose up -d\n"
    "  2. DATABASE_URL 是否正确？\n"
    "  3. 端口 5432 是否被占用？运行: docker ps\n"
)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                settings.DATABASE_URL, min_size=1, max_size=5, command_timeout=15,
            )
        except (OSError, asyncpg.exceptions.PostgresError) as e:
            logger.critical("%s  原始错误: %s", _DB_CONNECT_HELP, e)
            raise SystemExit(1) from e
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
