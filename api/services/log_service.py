"""Auto-logging service — appends timestamped entries to the Log wiki page
in each knowledge base as events occur (uploads, extractions, edits, deletes).
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_LOG_FILENAME = "log.md"
_LOG_PATH = "/wiki/"

# Entry format: ## [YYYY-MM-DD] <emoji> | <Event Type>\n- <detail>
_ENTRY_TEMPLATE = "\n## [{timestamp}] {emoji} | {event_type}\n{detail}\n"


async def _find_log(pool, kb_id: str) -> dict | None:
    """Return the Log wiki page row (id, content) or None."""
    return await pool.fetchrow(
        "SELECT id, content FROM documents "
        "WHERE knowledge_base_id = $1 AND path = $2 "
        "AND filename = $3 AND archived = false "
        "ORDER BY created_at LIMIT 1",
        kb_id, _LOG_PATH, _LOG_FILENAME,
    )


async def _append(pool, kb_id: str, user_id: str, emoji: str,
                  event_type: str, detail: str) -> None:
    """Append a log entry to the KB's Log page.  No-op if no Log page exists."""
    try:
        log_doc = await _find_log(pool, kb_id)
        if not log_doc:
            return  # KB has no Log page — skip silently

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
        entry = _ENTRY_TEMPLATE.format(
            timestamp=timestamp, emoji=emoji,
            event_type=event_type, detail=detail,
        )
        new_content = (log_doc["content"] or "") + entry

        await pool.execute(
            "UPDATE documents SET content = $1, version = version + 1, "
            "updated_at = now() WHERE id = $2",
            new_content, log_doc["id"],
        )
    except Exception:
        logger.exception("Failed to append log entry to KB %s", kb_id[:8])


# ── Public helpers ──

async def log_document_uploaded(pool, kb_id: str, user_id: str,
                                filename: str, doc_id: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="📥", event_type="Document Uploaded",
        detail=f"- `{filename}` ingested → `{doc_id[:8]}`")

async def log_note_created(pool, kb_id: str, user_id: str,
                           title: str, path: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="📝", event_type="Note Created",
        detail=f"- [{title}]({path}) created")

async def log_content_updated(pool, kb_id: str, user_id: str,
                              title: str, filename: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="✏️", event_type="Content Updated",
        detail=f"- `{filename}` ({title}) updated")

async def log_document_deleted(pool, kb_id: str, user_id: str,
                               filename: str, title: str = "",
                               count: int = 1) -> None:
    label = title or filename
    if count == 1:
        detail = f"- `{label}` archived"
    else:
        detail = f"- {count} documents archived (incl. `{label}`)"
    await _append(pool, kb_id, user_id,
        emoji="🗑️", event_type="Document Deleted",
        detail=detail)

async def log_extraction_approved(pool, kb_id: str, user_id: str,
                                  title: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="✅", event_type="Extraction Approved",
        detail=f"- Wiki page [{title}](/wiki/) created from extraction")

async def log_extraction_rejected(pool, kb_id: str, user_id: str,
                                  title: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="❌", event_type="Extraction Rejected",
        detail=f"- Extraction for `{title}` rejected")

async def log_wiki_created(pool, kb_id: str, user_id: str,
                           title: str, path: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="🤖", event_type="Wiki Page Created",
        detail=f"- [{title}]({path}) written via MCP")

async def log_wiki_edited(pool, kb_id: str, user_id: str,
                          path: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="✏️", event_type="Wiki Page Edited",
        detail=f"- `{path}` edited via MCP")

async def log_wiki_deleted(pool, kb_id: str, user_id: str,
                           filename: str, path: str) -> None:
    await _append(pool, kb_id, user_id,
        emoji="🗑️", event_type="Wiki Page Deleted",
        detail=f"- `{path}{filename}` deleted via MCP")
