"""Write file tool — create or overwrite files relative to WIKI_ROOT.

Supports three modes (mimicking Claude Code's Write + line-range Edit):
  1. Full overwrite:  write_file(path, content)
  2. Insert at line:  write_file(path, content, offset=N)
  3. Replace range:   write_file(path, content, offset=N, limit=M)
"""

import logging
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Write content to a file (creates, overwrites, or replaces a line range).

Three modes — pick the one you need:

  - **Full overwrite** (no offset/limit): Replace the entire file. Use when creating a new file or rewriting a small file completely.
  - **Insert at line** (offset only): Insert content at the given line, shifting existing lines down. offset=1 means prepend at the top.
  - **Replace range** (offset + limit): Replace `limit` lines starting at `offset` with the new content. Use together with read_file line numbers for precise edits.

Path is relative to WIKI_ROOT. Parent directories are created automatically."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File path relative to WIKI_ROOT, e.g. 'my-kb/wiki/summaries/paper.md'",
        },
        "content": {
            "type": "string",
            "description": "Content to write. In full-overwrite mode this is the entire file. In insert/replace modes this is the text to insert (can be one line or many lines).",
        },
        "offset": {
            "type": "integer",
            "description": "Line number (1-indexed) to start writing at. Use with 'limit' to replace a range, or alone to insert without removing. Omit for full-file overwrite.",
        },
        "limit": {
            "type": "integer",
            "description": "Number of lines to replace starting at 'offset'. Must be used together with 'offset'. Omit (or set to 0) to insert without removing any existing lines.",
        },
    },
    "required": ["path", "content"],
}


def execute(path: str, content: str, offset: int | None = None, limit: int | None = None) -> dict:
    """Write content to a file.

    Modes:
      - offset=None, limit=None  → full overwrite
      - offset=N, limit=None/0   → insert at line N (shift existing lines down)
      - offset=N, limit=M (>0)   → replace M lines starting at line N
    """
    full_path = WIKI_ROOT / path

    # Security: don't allow writing outside WIKI_ROOT
    try:
        full_path.resolve().relative_to(WIKI_ROOT.resolve())
    except ValueError:
        return {"error": f"Path '{path}' escapes WIKI_ROOT — rejected"}

    full_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Mode 1: Full overwrite ──
    if offset is None:
        full_path.write_text(content, encoding="utf-8")
        logger.info("wrote file: %s (%d chars, full overwrite)", path, len(content))
        return {"ok": True, "path": path, "size": len(content), "mode": "overwrite"}

    # ── Modes 2 & 3: Line-range insert/replace ──
    if offset < 1:
        return {"error": f"offset must be >= 1, got {offset}"}

    effective_limit = limit if (limit is not None and limit > 0) else 0

    # Read existing content (empty string if file doesn't exist)
    if full_path.exists():
        try:
            existing = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                existing = full_path.read_text(encoding="latin-1")
            except Exception as e:
                return {"error": f"Cannot decode existing file '{path}': {e}"}
    else:
        existing = ""

    existing_lines = existing.split("\n") if existing else []

    # Clamp offset to [1, len(lines)+1]
    # offset = len+1 means "append at end"
    offset = min(offset, len(existing_lines) + 1)

    # Ensure content ends with newline if inserting into an existing file
    # (so it cleanly separates from the shifted lines)
    insert_lines = content.split("\n")

    if effective_limit > 0:
        # Replace mode: remove `limit` lines starting at `offset`
        end = min(offset - 1 + effective_limit, len(existing_lines))
        new_lines = (
            existing_lines[: offset - 1]
            + insert_lines
            + existing_lines[end:]
        )
        mode = "replace"
    else:
        # Insert mode: insert at `offset`, shift everything down
        new_lines = (
            existing_lines[: offset - 1]
            + insert_lines
            + existing_lines[offset - 1 :]
        )
        mode = "insert"

    new_content = "\n".join(new_lines)
    full_path.write_text(new_content, encoding="utf-8")
    logger.info(
        "wrote file: %s (%d chars, %s at line %d, %d existing lines → %d)",
        path, len(content), mode, offset, len(existing_lines), len(new_lines),
    )
    return {
        "ok": True,
        "path": path,
        "size": len(content),
        "mode": mode,
        "offset": offset,
        "limit": effective_limit,
        "total_lines_after": len(new_lines),
    }
