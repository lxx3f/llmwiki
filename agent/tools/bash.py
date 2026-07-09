"""Bash tool — execute shell commands scoped to WIKI_ROOT."""

import asyncio
import logging
import subprocess
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Execute a bash command. The working directory is always WIKI_ROOT.
Use for: ls, find, grep (via rg), git, mkdir, python (including pdf_oxide PDF extraction), etc.
Not for: reading files (use read_file instead of cat),
        writing multi-line file content (use write_file instead),
        editing files (use edit_file instead),
        viewing images (use view_image instead)."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "The bash command to execute. Working directory is WIKI_ROOT.",
        },
    },
    "required": ["command"],
}


async def execute(command: str, timeout: float = 120.0) -> dict:
    """Execute a bash command with working directory = WIKI_ROOT."""
    full_cmd = f"cd {_quote(str(WIKI_ROOT))} && {command}"

    try:
        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1,
        }

    return {
        "stdout": stdout.decode("utf-8", errors="replace")[:50000],
        "stderr": stderr.decode("utf-8", errors="replace")[:10000],
        "exit_code": proc.returncode or 0,
    }


def _quote(path: str) -> str:
    """Single-quote a path for shell, handling Windows backslashes."""
    return f"'{path}'" if "\\" not in path else f'"{path}"'
