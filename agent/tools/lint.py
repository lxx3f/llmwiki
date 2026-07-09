"""Lint tool — scan a knowledge base for wiki health issues.

Returns deterministic, structured findings that the LLM can summarize:

  - stats              page count, source count
  - orphans            pages with no incoming references from other wiki pages
  - outdated           source documents modified after their last ingest commit
  - unindexed_pages    content pages that exist on disk but aren't in index.md
  - contradiction_ctx  for each top concept term from index.md, the snippets
                       that mention it across pages — the LLM judges whether
                       they actually contradict

This is a *data gatherer* — semantic judgement (is this really a contradiction?)
stays with the LLM, but the tool does all the file walking / grep / git work.
"""

import json
import logging
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Scan a knowledge base for wiki health issues.

Use this when the user asks for a health check, lint, or wiki review.
The tool runs deterministic checks (file walking, ripgrep, git log) and
returns structured findings; you (the LLM) summarize them into a report.

Args:
  action:    "scan" runs all checks. Specific actions: "stats" | "orphans"
             | "outdated" | "unindexed" | "contradiction_ctx".
  kb_slug:   Knowledge base slug (default: "main").

Returns:
  {
    "stats": {...},
    "orphans": [...],
    "outdated": [...],
    "unindexed": [...],
    "contradiction_ctx": {...},
  }
  Each section is omitted if not requested via `action` (or present for "scan")."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["scan", "stats", "orphans", "outdated", "unindexed", "contradiction_ctx"],
            "description": "Which check to run. 'scan' (default) runs all of them.",
            "default": "scan",
        },
        "kb_slug": {
            "type": "string",
            "description": "Knowledge base slug. Default: 'main'.",
            "default": "main",
        },
    },
    "required": [],
}

# Page files that are never content pages (system/control files)
SYSTEM_PAGES = {"index.md", "log.md", "overview.md"}
# Link pattern: [[concepts/foo]] or [[foo]] or [[foo|alias]]
LINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:[#\|][^\]]*)?\]\]")


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command in WIKI_ROOT (or `cwd`) and return stdout."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=str(cwd or WIKI_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _kb_paths(kb_slug: str) -> tuple[Path, Path, Path]:
    """Return (kb_dir, wiki_dir, sources_dir) for a given kb_slug."""
    kb = WIKI_ROOT / kb_slug
    return kb, kb / "wiki", kb / "sources"


def _list_wiki_pages(wiki_dir: Path) -> list[Path]:
    """All .md files under wiki/, excluding system pages."""
    if not wiki_dir.is_dir():
        return []
    pages = []
    for p in wiki_dir.rglob("*.md"):
        if p.name in SYSTEM_PAGES:
            continue
        if p.name == ".gitkeep":
            continue
        pages.append(p)
    return sorted(pages)


# ── Checks ─────────────────────────────────────────────────────


def _stats(wiki_dir: Path, sources_dir: Path) -> dict:
    pages = _list_wiki_pages(wiki_dir)
    src_count = sum(1 for d in sources_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    by_kind = defaultdict(int)
    for p in pages:
        rel = p.relative_to(wiki_dir)
        top = rel.parts[0] if len(rel.parts) > 1 else "root"
        by_kind[top] += 1
    return {
        "page_count": len(pages),
        "source_count": src_count,
        "pages_by_dir": dict(by_kind),
    }


def _orphans(wiki_dir: Path) -> list[dict]:
    """Pages with no incoming [[link]] from any other page (or from index.md)."""
    pages = _list_wiki_pages(wiki_dir)
    if not pages:
        return []

    # Build set of all linked targets across wiki/, normalized (lowercase, no .md).
    # Handles both [[path/to/foo]] and [[path/to/foo.md]] wiki-link styles.
    linked_targets: set[str] = set()
    for p in wiki_dir.rglob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in LINK_PATTERN.finditer(text):
            target = m.group(1).strip().lower()
            if target.endswith(".md"):
                target = target[:-3]
            linked_targets.add(target)

    orphans = []
    for p in pages:
        rel = p.relative_to(wiki_dir).as_posix()  # "concepts/transformer.md"
        stem = p.stem                              # "transformer"
        rel_no_ext = rel[: -len(".md")]            # "concepts/transformer"
        if (rel_no_ext.lower() in linked_targets
                or stem.lower() in linked_targets
                or rel.lower() in linked_targets):  # "concepts/transformer.md" raw
            continue
        orphans.append({"path": f"{wiki_dir.parent.name}/{rel}", "incoming_refs": 0})
    return orphans


def _outdated(sources_dir: Path) -> list[dict]:
    """Sources whose last commit is more recent than the last ingest commit."""
    if not sources_dir.is_dir():
        return []

    # Sources live under {kb}/sources/, not just sources/. We compute the
    # relative path from WIKI_ROOT so git log can find them.
    kb_slug = sources_dir.parent.name
    outdated = []
    for d in sorted(sources_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        doc_id = d.name
        doc_path = f"{kb_slug}/sources/{doc_id}/"
        last_ingest = _git(
            "log", "master", "--grep", f"ingest: {doc_id}",
            "--format=%H", "-1",
        ).strip()
        last_source = _git(
            "log", "master", "--format=%H", "-1", "--", doc_path,
        ).strip()
        if not last_source:
            # Source dir exists but never committed
            outdated.append({
                "doc_id": doc_id,
                "reason": "never committed to git",
            })
            continue
        if not last_ingest:
            outdated.append({
                "doc_id": doc_id,
                "reason": "no ingest commit found",
            })
            continue
        if last_source != last_ingest:
            outdated.append({
                "doc_id": doc_id,
                "reason": "source modified after last ingest",
                "last_ingest": last_ingest[:8],
                "last_source": last_source[:8],
            })
    return outdated


def _unindexed(wiki_dir: Path) -> list[dict]:
    """Content pages that exist on disk but aren't referenced from index.md."""
    pages = _list_wiki_pages(wiki_dir)
    if not pages:
        return []
    index_path = wiki_dir / "index.md"
    if not index_path.is_file():
        return [{"path": str(p.relative_to(wiki_dir.parent)),
                 "reason": "index.md missing"} for p in pages]

    try:
        index_text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Extract every link target from index.md, normalized (lowercase, no .md suffix).
    # Handles both [[path/to/foo]] and [[path/to/foo.md]] wiki-link styles, plus
    # plain markdown links [text](path/to/foo.md).
    indexed: set[str] = set()
    for m in LINK_PATTERN.finditer(index_text):
        target = m.group(1).strip().lower()
        if target.endswith(".md"):
            target = target[:-3]
        indexed.add(target)
    for m in re.finditer(r"\]\(([^)]+\.md)\)", index_text):
        target = m.group(1).strip().lower()[:-3]
        indexed.add(target)

    missing = []
    for p in pages:
        rel = p.relative_to(wiki_dir).as_posix()  # "concepts/foo.md"
        rel_no_ext = rel[: -len(".md")]            # "concepts/foo"
        if (rel_no_ext.lower() in indexed
                or p.stem.lower() in indexed
                or rel.lower() in indexed):         # "concepts/foo.md" raw
            continue
        missing.append({
            "path": f"{wiki_dir.parent.name}/{rel}",
            "reason": "not referenced from index.md",
        })
    return missing


def _contradiction_ctx(wiki_dir: Path, top_n: int = 12, max_snippets: int = 4) -> dict:
    """For each top concept term (extracted from index.md), gather snippets
    that mention it from across the wiki. The LLM judges if they conflict.

    Top terms = the most prominent link targets in index.md, in order.
    """
    index_path = wiki_dir / "index.md"
    if not index_path.is_file():
        return {"_error": "index.md not found"}

    # Count term frequency in index.md
    term_count: dict[str, int] = defaultdict(int)
    try:
        idx_text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"_error": "cannot read index.md"}
    for m in LINK_PATTERN.finditer(idx_text):
        target = m.group(1).strip()
        # Use the basename as the "concept term"
        term = target.split("/")[-1].lower()
        term_count[term] += 1

    # Take top N terms (skip super short / common words)
    STOP = {"the", "and", "for", "with", "from", "this", "that", "into", "see", "use"}
    candidates = sorted(term_count.items(), key=lambda kv: -kv[1])
    top_terms = [t for t, _ in candidates if len(t) >= 4 and t not in STOP][:top_n]
    if not top_terms:
        return {"_note": "no significant terms found in index.md"}

    # For each top term, find pages that mention it and grab a snippet per page
    out: dict[str, list[dict]] = {}
    for term in top_terms:
        pages_with_term: list[dict] = []
        for p in wiki_dir.rglob("*.md"):
            if p.name in SYSTEM_PAGES or p.name == ".gitkeep":
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if term not in text.lower():
                continue
            # Find a representative snippet (first line that contains the term)
            for line in text.splitlines():
                if term in line.lower() and len(line.strip()) > 20:
                    pages_with_term.append({
                        "page": f"{wiki_dir.parent.name}/{p.relative_to(wiki_dir).as_posix()}",
                        "snippet": line.strip()[:200],
                    })
                    break
            if len(pages_with_term) >= max_snippets:
                break
        if len(pages_with_term) >= 2:
            out[term] = pages_with_term
    return out


# ── Entry point ────────────────────────────────────────────────


def execute(action: str = "scan", kb_slug: str = "main") -> dict:
    """Run the requested lint check(s) and return structured findings."""
    kb_dir, wiki_dir, sources_dir = _kb_paths(kb_slug)
    if not kb_dir.is_dir():
        return {"error": f"knowledge base not found: {kb_slug}"}

    result: dict = {}
    actions = ["stats", "orphans", "outdated", "unindexed", "contradiction_ctx"] \
        if action == "scan" else [action]

    if "stats" in actions:
        result["stats"] = _stats(wiki_dir, sources_dir)
    if "orphans" in actions:
        result["orphans"] = _orphans(wiki_dir)
    if "outdated" in actions:
        result["outdated"] = _outdated(sources_dir)
    if "unindexed" in actions:
        result["unindexed"] = _unindexed(wiki_dir)
    if "contradiction_ctx" in actions:
        result["contradiction_ctx"] = _contradiction_ctx(wiki_dir)

    result["_meta"] = {
        "kb_slug": kb_slug,
        "wiki_root": str(WIKI_ROOT),
        "actions_run": actions,
    }
    return result
