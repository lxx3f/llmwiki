"""Manifest tool — read/write a per-doc .manifest.json describing file roles.

The manifest tells the ingest agent which files are:
  - "main"        : the primary document, may produce a new summary page
  - "supplement"  : additional context that should be merged into the main
                    summary (not turned into its own summary page)
  - "asset"       : images/figures/attachments — referenced from wiki pages
                    but never trigger an ingest by themselves

This solves two problems:
  1. Images and attachments are no longer mistaken for independent documents.
  2. Long documents or supplementary materials are merged into one wiki
     page instead of producing redundant summaries.

Manifest format (sources/{doc_id}/.manifest.json):
{
  "doc_id": "005__paper",
  "files": {
    "paper.pdf":                {"role": "main"},
    "images/fig1.png":          {"role": "asset"},
    "appendix-supplementary.md":{"role": "supplement"}
  }
}
"""

import hashlib
import json
import logging
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

# ── Heuristics: how to classify a file when no manifest exists ──

ASSET_DIR_NAMES = {"images", "img", "figures", "figs", "assets", "attachments", "media"}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp", ".ico"}
MAIN_BASENAMES = {"source", "article", "paper", "document", "doc", "main", "readme", "笔记", "文章"}
# Heuristic: if extension is text-y AND not in asset dir AND not in asset exts,
# treat as supplement (safer default than main — the agent can promote it).

MANIFEST_FILENAME = ".manifest.json"

DESCRIPTION = """Read or update a per-document manifest at sources/{doc_id}/.manifest.json.

The manifest classifies each file's role:
  - "main":       the primary document. Triggers a new summary page (or re-ingest).
  - "supplement": additional context. Merged into the main summary, not a new page.
  - "asset":      images / figures / attachments. Referenced from wiki pages
                  but never trigger an ingest on their own.

Use this tool:
  - read_manifest(path=...)      to inspect a doc's classification before deciding what to write
  - write_manifest(path=..., content=...)  to set roles explicitly
  - infer_manifest(path=...)     to auto-classify by filename/dir heuristics (no manifest exists yet)

Path is relative to WIKI_ROOT, e.g. "my-kb/sources/005__paper"."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["read", "write", "infer"],
            "description": "read: return current manifest (or generated if missing). write: set explicit manifest. infer: auto-classify files via heuristics and return suggested manifest (does not write).",
        },
        "path": {
            "type": "string",
            "description": "Doc dir relative to WIKI_ROOT, e.g. 'my-kb/sources/005__paper'.",
        },
        "content": {
            "type": "string",
            "description": "(action=write) JSON content of the manifest. Must be a JSON object with structure {doc_id, files: {relpath: {role: 'main'|'supplement'|'asset'}}}.",
        },
    },
    "required": ["action", "path"],
}


def _doc_dir(path: str) -> Path:
    """Resolve a manifest path to an absolute doc directory under WIKI_ROOT."""
    p = (WIKI_ROOT / path).resolve()
    try:
        p.relative_to(WIKI_ROOT.resolve())
    except ValueError:
        raise ValueError(f"path {path!r} escapes WIKI_ROOT")
    if not p.is_dir():
        raise FileNotFoundError(f"not a directory: {path}")
    return p


def _manifest_path(doc_dir: Path) -> Path:
    return doc_dir / MANIFEST_FILENAME


def _file_sha256(p: Path) -> str:
    """SHA256 of a file's bytes. Returns '' for empty files."""
    h = hashlib.sha256()
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _classify(rel: str, name_lower: str) -> str:
    """Heuristic file classification when no manifest exists.

    Rules (first match wins):
      1. Parent dir is images/img/figures/etc. → asset
      2. Extension is .png/.jpg/.gif/etc.      → asset
      3. Basename matches 'source'/'article'/…  → main
      4. Otherwise (other text files)           → supplement
    """
    parts = Path(rel).parts
    if any(part.lower() in ASSET_DIR_NAMES for part in parts[:-1]):
        return "asset"
    if Path(rel).suffix.lower() in ASSET_EXTENSIONS:
        return "asset"
    stem = Path(rel).stem.lower()
    if stem in MAIN_BASENAMES:
        return "main"
    # PDF/DOCX files with no other main heuristic: treat first one as main
    # so a single PDF in a doc dir is still recognized as the main document.
    if Path(rel).suffix.lower() in {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".epub"}:
        return "main"
    return "supplement"


def infer_manifest(doc_dir: Path) -> dict:
    """Generate a manifest via heuristics. Does not write to disk."""
    files: dict[str, dict] = {}
    for p in sorted(doc_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.name == MANIFEST_FILENAME:
            continue
        rel = p.relative_to(doc_dir).as_posix()
        role = _classify(rel, p.name.lower())
        entry: dict = {"role": role}
        sha = _file_sha256(p)
        if sha:
            entry["sha256"] = sha
        files[rel] = entry
    return {
        "doc_id": doc_dir.name,
        "files": files,
        "_note": "auto-inferred by heuristics; edit to override",
    }


def read_manifest(doc_dir: Path) -> dict:
    """Return current manifest, or generate one via heuristics if missing."""
    mp = _manifest_path(doc_dir)
    if mp.is_file():
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
            data.setdefault("doc_id", doc_dir.name)
            data.setdefault("files", {})
            data["_source"] = "on-disk"
            return data
        except json.JSONDecodeError as e:
            return {
                "error": f"manifest exists but invalid JSON: {e}",
                "doc_id": doc_dir.name,
                "files": {},
            }
    inferred = infer_manifest(doc_dir)
    inferred["_source"] = "inferred (no .manifest.json found)"
    return inferred


def write_manifest(doc_dir: Path, content: str) -> dict:
    """Validate and write manifest JSON. Adds sha256 to each file entry."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return {"error": f"content is not valid JSON: {e}"}
    if not isinstance(data, dict):
        return {"error": "manifest must be a JSON object"}

    files = data.get("files", {})
    if not isinstance(files, dict):
        return {"error": "'files' must be an object"}

    valid_roles = {"main", "supplement", "asset"}
    normalized: dict[str, dict] = {}
    for rel, entry in files.items():
        if not isinstance(entry, dict):
            return {"error": f"files['{rel}'] must be an object"}
        role = entry.get("role")
        if role not in valid_roles:
            return {"error": f"files['{rel}'].role must be one of {valid_roles}, got {role!r}"}
        normalized[rel] = {"role": role}

    # Fill in sha256 for files that exist
    for rel, entry in normalized.items():
        p = doc_dir / rel
        if p.is_file():
            sha = _file_sha256(p)
            if sha:
                entry["sha256"] = sha

    out = {
        "doc_id": data.get("doc_id", doc_dir.name),
        "files": normalized,
    }
    _manifest_path(doc_dir).write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("wrote manifest: %s (%d files)", doc_dir, len(normalized))
    return {"ok": True, "manifest": out, "written_to": str(_manifest_path(doc_dir))}


def execute(action: str, path: str, content: str = "") -> dict:
    """Dispatch manifest read/write/infer."""
    try:
        doc_dir = _doc_dir(path)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}

    if action == "read":
        return read_manifest(doc_dir)
    elif action == "infer":
        m = infer_manifest(doc_dir)
        m["_note"] = "inferred (NOT written — call action=write to persist)"
        return m
    elif action == "write":
        return write_manifest(doc_dir, content)
    else:
        return {"error": f"unknown action: {action}"}
