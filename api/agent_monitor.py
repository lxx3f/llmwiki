"""Agent monitor — read state file, log tail, and git history for the dashboard."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Project root (where the agent/ dir lives)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = _PROJECT_ROOT / "agent"
STATE_FILE = AGENT_DIR / ".state.json"
LOG_FILE = AGENT_DIR / "agent.log"


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


def read_log_tail(n: int = 30) -> list[str]:
    """Last n lines of agent.log. Returns [] if missing."""
    if not LOG_FILE.is_file():
        return []
    try:
        # Use python to avoid platform-specific tail
        with LOG_FILE.open("rb") as f:
            try:
                f.seek(0, 2)  # end
                size = f.tell()
                # Read up to ~64KB from end, then split into lines
                read_size = min(size, 64 * 1024)
                f.seek(size - read_size)
                data = f.read().decode("utf-8", errors="replace")
            except OSError:
                return []
        lines = data.splitlines()
        return lines[-n:] if len(lines) > n else lines
    except OSError:
        return []


def parse_log_level(line: str) -> str:
    """Extract log level from a formatted line. Returns 'INFO' if unknown."""
    if "[ERROR]" in line:
        return "ERROR"
    if "[WARNING]" in line:
        return "WARNING"
    if "[INFO]" in line:
        return "INFO"
    if "[DEBUG]" in line:
        return "DEBUG"
    return ""


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
