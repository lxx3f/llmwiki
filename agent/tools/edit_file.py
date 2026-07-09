"""Edit file tool — precise string replace for updating existing files."""

import logging
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Replace text in an existing file. old_text must match exactly once.
Use for: updating index.md entries, editing log.md, modifying an existing wiki page.
If old_text matches 0 times, the tool returns an error.
If old_text matches more than once, the tool returns an error with match locations.
Path is relative to WIKI_ROOT."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File path relative to WIKI_ROOT",
        },
        "old_text": {
            "type": "string",
            "description": "Exact text to replace (must match exactly once)",
        },
        "new_text": {
            "type": "string",
            "description": "Replacement text",
        },
    },
    "required": ["path", "old_text", "new_text"],
}


def execute(path: str, old_text: str, new_text: str) -> dict:
    """Replace old_text with new_text in file. Requires exactly one match."""
    full_path = WIKI_ROOT / path

    # Security
    try:
        full_path.resolve().relative_to(WIKI_ROOT.resolve())
    except ValueError:
        return {"error": f"Path '{path}' escapes WIKI_ROOT — rejected"}

    if not full_path.exists():
        return {"error": f"File not found: {path}"}

    content = full_path.read_text(encoding="utf-8")

    count = content.count(old_text)
    if count == 0:
        return {"error": f"old_text not found in {path}. No match."}
    if count > 1:
        # Find line numbers of matches
        lines = content.split("\n")
        positions = []
        offset = 0
        for i, line in enumerate(lines, 1):
            idx = line.find(old_text.split("\n")[0])
            if idx >= 0:
                positions.append(f"  line {i}: ...{line[max(0,idx-10):idx+20].strip()}...")
        return {
            "error": f"old_text matched {count} times in {path}. Must match exactly once. Matches at:\n"
            + "\n".join(positions[:5])
        }

    new_content = content.replace(old_text, new_text, 1)
    full_path.write_text(new_content, encoding="utf-8")
    logger.info("edited file: %s", path)
    return {"ok": True, "path": path}
