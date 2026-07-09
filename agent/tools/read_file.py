"""Read file tool — read file contents directly via OS, no shell.

Mimics Claude Code's Read tool: direct file I/O with line numbers,
pagination (offset/limit), and encoding handling.
"""

import logging
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Read content from a file with line numbers. Returns the file content directly — no shell involved.
Use for: reading wiki pages, source documents, index.md, log.md, overview.md, any text file.
Use this instead of 'bash cat' whenever you need to read a file — it's faster and safer.
For images, use view_image instead. For directory listings, use bash ls.
Path is relative to WIKI_ROOT."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File path relative to WIKI_ROOT, e.g. 'my-kb/wiki/index.md' or 'my-kb/sources/001__paper/article.md'",
        },
        "offset": {
            "type": "integer",
            "description": "Line number to start reading from (1-indexed). Default: 1 (start of file). Use when the file is very long and you only need part of it.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of lines to read. Default: 500. Set higher for long files, set lower for quick peeks.",
        },
    },
    "required": ["path"],
}

# Default read limits
DEFAULT_LIMIT = 500
MAX_OUTPUT_CHARS = 120_000  # Cap to avoid blowing up context


def execute(path: str, offset: int = 1, limit: int = DEFAULT_LIMIT) -> dict:
    """Read a file and return its content with line numbers.

    Args:
        path: File path relative to WIKI_ROOT.
        offset: Line number to start from (1-indexed).
        limit: Max lines to return (0 = unlimited, capped for safety).

    Returns:
        A dict with keys: path, content, total_lines, start_line, end_line, truncated
    """
    full_path = WIKI_ROOT / path

    # Security: don't allow reading outside WIKI_ROOT
    try:
        full_path.resolve().relative_to(WIKI_ROOT.resolve())
    except ValueError:
        return {"error": f"Path '{path}' escapes WIKI_ROOT — rejected"}

    if not full_path.exists():
        return {"error": f"File not found: {path}"}

    if full_path.is_dir():
        return {"error": f"'{path}' is a directory, not a file. Use bash ls to list its contents."}

    try:
        raw = full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Try with a more lenient encoding
        try:
            raw = full_path.read_text(encoding="latin-1")
        except Exception as e:
            return {"error": f"Cannot decode file '{path}' as text: {e}"}
    except Exception as e:
        return {"error": f"Failed to read '{path}': {e}"}

    all_lines = raw.split("\n")
    total_lines = len(all_lines)

    # Validate offset
    offset = max(1, offset)
    if offset > total_lines:
        return {
            "path": path,
            "content": "",
            "total_lines": total_lines,
            "start_line": offset,
            "end_line": offset,
            "note": f"offset {offset} exceeds file length {total_lines}",
        }

    # Apply limit (0 = no limit, but we still cap for safety)
    effective_limit = limit if limit > 0 else DEFAULT_LIMIT * 4
    end = min(offset - 1 + effective_limit, total_lines)
    selected = all_lines[offset - 1 : end]

    # Format with line numbers (like cat -n)
    numbered_lines = []
    char_count = 0
    actual_end = offset - 1

    for i, line in enumerate(selected, start=offset):
        numbered = f"{i}\t{line}"
        numbered_lines.append(numbered)
        char_count += len(numbered) + 1  # +1 for newline
        actual_end = i
        if char_count > MAX_OUTPUT_CHARS:
            break

    truncated = actual_end < end
    content = "\n".join(numbered_lines)

    logger.info(
        "read file: %s (lines %d-%d/%d, %d chars%s)",
        path, offset, actual_end, total_lines, char_count,
        " [truncated]" if truncated else "",
    )

    return {
        "path": path,
        "content": content,
        "total_lines": total_lines,
        "start_line": offset,
        "end_line": actual_end,
        "truncated": truncated,
    }
