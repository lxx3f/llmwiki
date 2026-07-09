"""Agent monitor — read state file, log tail, and git history for the dashboard."""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Project root (where the agent/ dir lives)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = _PROJECT_ROOT / "agent"
STATE_FILE = AGENT_DIR / ".state.json"

# Log directory — mirror agent/config.py's resolution so writer and reader agree.
LOG_DIR = Path(os.getenv("AGENT_LOG_DIR", "./logs/"))
if not LOG_DIR.is_absolute():
    LOG_DIR = (_PROJECT_ROOT / LOG_DIR).resolve()
LOG_FILE = Path(os.getenv("AGENT_LOG_FILE", str(LOG_DIR / "agent.log")))
LOG_ERROR_FILE = Path(os.getenv("AGENT_LOG_ERROR_FILE", str(LOG_DIR / "agent.errors.log")))


def _wiki_root() -> Path:
    """Resolve WIKI_ROOT from the api config. Same logic as api/main.py."""
    from config import settings
    p = Path(settings.WIKI_ROOT)
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()
    return p


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command, return stdout. Empty on failure."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=str(cwd or _wiki_root()),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def read_state() -> dict:
    """Read agent/.state.json. Returns idle default if missing."""
    if not STATE_FILE.is_file():
        return {"state": "unknown", "last_update": None, "current_doc": "", "branch": "", "round": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "unknown", "last_update": None, "current_doc": "", "branch": "", "round": 0}


def is_stale(state: dict, threshold_seconds: int = 300) -> bool:
    """True if state=running but last_update older than threshold (likely crashed)."""
    if state.get("state") != "running":
        return False
    last = state.get("last_update")
    if not last:
        return True
    try:
        ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age > threshold_seconds


def read_log_tail(n: int = 30, level_filter: str = "all") -> list[str]:
    """Last n lines of agent.log (across rotations), optionally filtered by level.

    Rotated files (agent.log.YYYY-MM-DD) are included in chronological order
    so the tail reflects the most recent activity across days.

    level_filter: "all" | "warn" | "error"
      - "all":   no filtering
      - "warn":  WARNING and ERROR only
      - "error": ERROR only
    """
    lines = _read_rotated_tail(LOG_FILE, n * 4)  # overshoot before filter
    if level_filter != "all":
        keep = {"warn": {"WARNING", "ERROR"},
                "error": {"ERROR"}}.get(level_filter, set())
        lines = [ln for ln in lines if parse_log_level(ln) in keep]
    return lines[-n:] if len(lines) > n else lines


def read_errors_tail(n: int = 30) -> list[str]:
    """Last n lines from agent.errors.log (across weekly rotations)."""
    return _read_rotated_tail(LOG_ERROR_FILE, n)


def _read_rotated_tail(path: Path, n: int) -> list[str]:
    """Read last n lines from a log file, including its rotated siblings.

    Reads up to 256KB from the end of the active file. If that's not enough
    to satisfy n lines, falls back to rotated files (most recent first).
    """
    candidates = _rotated_files(path)
    out: list[str] = []
    for fp in candidates:
        if not fp.is_file():
            continue
        chunk = _tail_lines(fp, 256 * 1024)
        # Prepend (oldest first within file), so overall order remains chronological.
        out = chunk + out
        if len(out) >= n:
            break
    return out[-n:] if len(out) > n else out


def _rotated_files(path: Path) -> list[Path]:
    """Return [rotated_oldest..rotated_newest, active] in chronological order.

    Active file is at the end. Rotated siblings (e.g. agent.log.2026-07-09)
    are returned in ascending name order, which for date-based suffixes
    also gives chronological order.
    """
    parent = path.parent
    stem = path.name
    rotated = sorted(parent.glob(f"{stem}.*"))
    return rotated + [path]


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    """Read up to max_bytes from the end of `path`, return as list of lines."""
    try:
        with path.open("rb") as f:
            try:
                f.seek(0, 2)
                size = f.tell()
                if size == 0:
                    return []
                read_size = min(size, max_bytes)
                f.seek(size - read_size)
                data = f.read().decode("utf-8", errors="replace")
            except OSError:
                return []
        return data.splitlines()
    except OSError:
        return []


def parse_log_level(line: str) -> str:
    """Extract log level from a formatted line. Returns '' if unknown."""
    m = re.search(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]", line)
    return m.group(1) if m else ""


def recent_ingests(limit: int = 10) -> list[dict]:
    """Parse recent ingest commits from git log. Returns list of {hash, date, message, doc_id}."""
    import re
    raw = _git(
        "log", "master",
        "--grep", "ingest: ",
        f"--format=%H%x1f%cI%x1f%s",
        f"-n", str(limit),
    )
    out = []
    # Match "ingest: <doc_id> ..." — doc_id is the next whitespace-delimited
    # token after the colon, optionally followed by ' — title' or ' [agent v...]'.
    pat = re.compile(r"^ingest:\s+(\S+)(?:\s+[—\-]\s+|\s+\[agent\s+v|$)")
    for line in raw.splitlines():
        if "\x1f" not in line:
            continue
        h, date, msg = line.split("\x1f", 2)
        m = pat.match(msg)
        doc_id = m.group(1) if m else ""
        out.append({
            "hash": h[:8],
            "date": date,
            "message": msg,
            "doc_id": doc_id,
        })
    return out


def list_kbs() -> list[dict]:
    """List knowledge bases from WIKI_ROOT. Each is a subdir with .kb.json."""
    root = _wiki_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta_path = d / ".kb.json"
        slug = d.name
        # Count sources
        sources_dir = d / "sources"
        source_count = sum(
            1 for sd in sources_dir.iterdir()
            if sd.is_dir() and not sd.name.startswith(".")
        ) if sources_dir.is_dir() else 0
        # Count wiki pages
        wiki_dir = d / "wiki"
        page_count = 0
        if wiki_dir.is_dir():
            for p in wiki_dir.rglob("*.md"):
                if p.name in {"index.md", "log.md", "overview.md"} or p.name == ".gitkeep":
                    continue
                page_count += 1
        out.append({
            "slug": slug,
            "name": slug,
            "source_count": source_count,
            "page_count": page_count,
        })
    return out


def pending_docs(kb_slug: str = "main") -> list[str]:
    """Doc dirs without an ingest commit on master."""
    sources_dir = _wiki_root() / kb_slug / "sources"
    if not sources_dir.is_dir():
        return []
    pending = []
    for d in sorted(sources_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        doc_id = d.name
        # Check if any ingest commit exists
        result = _git(
            "log", "master", "--grep", f"ingest: {doc_id}",
            "--format=%H", "-1",
        ).strip()
        if not result:
            pending.append(doc_id)
    return pending
