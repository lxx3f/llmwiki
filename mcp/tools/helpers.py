import os
import logging
from fnmatch import fnmatch
from pathlib import Path

from mcp.server.fastmcp import Context

from config import settings

logger = logging.getLogger(__name__)

MAX_LIST = 50
MAX_SEARCH = 20


def get_user_id(ctx: Context) -> str:
    """Single-user mode: return the configured user ID."""
    return settings.SINGLE_USER_ID


def deep_link(kb_slug: str, path: str, filename: str) -> str:
    full = (path.rstrip("/") + "/" + filename).lstrip("/")
    return f"{settings.APP_URL}/wikis/{kb_slug}/{full}"


def glob_match(filepath: str, pattern: str) -> bool:
    return fnmatch(filepath, pattern)


def resolve_path(path: str) -> tuple[str, str]:
    path_clean = path.lstrip("/")
    if "/" in path_clean:
        dir_path = "/" + path_clean.rsplit("/", 1)[0] + "/"
        filename = path_clean.rsplit("/", 1)[1]
    else:
        dir_path = "/"
        filename = path_clean
    return dir_path, filename


async def resolve_kb(user_id: str, slug: str) -> dict | None:
    from db import queryrow
    return await queryrow(
        "SELECT id, name, slug FROM knowledge_bases WHERE slug = $1",
        slug,
    )


def _resolve_local_path(key: str) -> Path:
    """Resolve a storage key to a local file path."""
    root = Path(settings.STORAGE_ROOT).resolve()
    safe_key = key.replace("\\", "/").lstrip("/")
    return (root / safe_key).resolve()


async def load_local_file(key: str) -> bytes | None:
    """Load a file from local storage."""
    import asyncio
    file_path = _resolve_local_path(key)
    if not file_path.is_file():
        logger.warning("Local file not found: %s", key)
        return None
    try:
        return await asyncio.to_thread(file_path.read_bytes)
    except Exception as e:
        logger.warning("Failed to load local file %s: %s", key, e)
        return None


def parse_page_range(pages_str: str, max_page: int) -> list[int]:
    result = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            s, e = int(start.strip()), int(end.strip())
            for p in range(max(1, s), min(max_page, e) + 1):
                result.add(p)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_page:
                result.add(p)
    return sorted(result)
