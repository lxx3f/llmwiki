"""Lightweight log helper for MCP-side event logging.
Mirrors api/services/log_service.py but uses the MCP db module.
"""

import logging
from datetime import datetime, timezone

from db import queryrow, execute

logger = logging.getLogger(__name__)

_LOG_PATH = "/wiki/"
_LOG_FILENAME = "log.md"
_ENTRY = "\n## [{ts}] {emoji} | {event}\n{detail}\n"


async def _append(kb_id: str, emoji: str, event: str, detail: str) -> None:
    try:
        doc = await queryrow(
            "SELECT id, content FROM documents "
            "WHERE knowledge_base_id = $1 AND path = $2 "
            "AND filename = $3 AND archived = false "
            "ORDER BY created_at LIMIT 1",
            kb_id, _LOG_PATH, _LOG_FILENAME,
        )
        if not doc:
            return

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        new_content = (doc["content"] or "") + _ENTRY.format(
            ts=ts, emoji=emoji, event=event, detail=detail,
        )
        await execute(
            "UPDATE documents SET content = $1, version = version + 1, "
            "updated_at = now() WHERE id = $2",
            new_content, doc["id"],
        )
    except Exception:
        logger.exception("MCP log append failed for KB %s", kb_id[:8])


async def log_wiki_created(kb_id: str, title: str, path: str) -> None:
    await _append(kb_id, "🤖", "Wiki Page Created",
                  f"- [{title}]({path}) written via MCP")


async def log_wiki_edited(kb_id: str, path: str) -> None:
    await _append(kb_id, "✏️", "Wiki Page Edited",
                  f"- `{path}` edited via MCP")


async def log_wiki_deleted(kb_id: str, filename: str, path: str) -> None:
    await _append(kb_id, "🗑️", "Wiki Page Deleted",
                  f"- `{path}{filename}` deleted via MCP")
