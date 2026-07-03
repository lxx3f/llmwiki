"""LLM Wiki — minimal web display and review layer.

The Agent operates directly on the filesystem + Git.
This server only renders wiki content (read-only) and provides
a review UI for accepting/rejecting Agent-proposed changes.
"""

import logging
import os
import subprocess
from pathlib import Path

# ── Fix broken SSL_CERT_FILE on conda/Windows ──
_ssl_cert = os.environ.get("SSL_CERT_FILE", "")
if not _ssl_cert or not os.path.isfile(_ssl_cert):
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────

WIKI_ROOT = Path(os.getenv("WIKI_ROOT", "./wiki_data/")).resolve()


def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess | None:
    """Run a git command in WIKI_ROOT. Returns None on timeout or unexpected error."""
    workdir = str(cwd or WIKI_ROOT)
    try:
        return subprocess.run(
            ["git"] + list(args),
            cwd=workdir,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Git command failed: git %s — %s", " ".join(args), e)
        return None


# ── App ──────────────────────────────────────────────────────

app = FastAPI(title="LLM Wiki")

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# ── Wiki browsing ────────────────────────────────────────────


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """List knowledge bases (directories that contain a wiki/ subdir)."""
    kbs = []
    if WIKI_ROOT.exists():
        for d in sorted(WIKI_ROOT.iterdir()):
            if d.is_dir() and (d / "wiki").is_dir():
                kbs.append({
                    "slug": d.name,
                    "name": d.name,
                    "wiki_count": len(list((d / "wiki").rglob("*.md"))),
                    "source_count": len(
                        [sd for sd in (d / "sources").iterdir() if sd.is_dir()]
                    ) if (d / "sources").exists() else 0,
                })
    return templates.TemplateResponse("index.html", {
        "request": request,
        "kbs": kbs,
        "active_page": "home",
    })


@app.get("/wiki/{slug}", response_class=HTMLResponse)
async def wiki_detail_page(
    request: Request,
    slug: str,
    page: str = Query(None),
):
    """Browse a wiki — show directory tree and render selected .md file."""
    kb_dir = WIKI_ROOT / slug
    if not kb_dir.is_dir() or not (kb_dir / "wiki").is_dir():
        return HTMLResponse("Knowledge base not found", status_code=404)

    wiki_dir = kb_dir / "wiki"

    # Build file tree
    wiki_files = []
    for f in sorted(wiki_dir.rglob("*.md")):
        rel = str(f.relative_to(wiki_dir)).replace("\\", "/")
        wiki_files.append({
            "path": rel,
            "name": f.stem,
            "dir": str(f.parent.relative_to(wiki_dir)).replace("\\", "/").replace(".", ""),
        })

    # Build source list
    sources = []
    sources_dir = kb_dir / "sources"
    if sources_dir.exists():
        for d in sorted(sources_dir.iterdir()):
            if d.is_dir():
                files = [f.name for f in d.iterdir() if f.is_file()]
                sources.append({"id": d.name, "name": d.name, "files": files})

    # Active page content
    active = None
    target = page.lstrip("/") if page else "index.md"
    target_path = wiki_dir / target
    if target_path.exists() and target_path.suffix == ".md":
        content = target_path.read_text(encoding="utf-8", errors="replace")
        import mistune

        md = mistune.create_markdown(plugins=[
            "table", "strikethrough", "footnotes", "task_lists", "url",
        ])
        active = {
            "path": target,
            "name": target_path.stem,
            "content": md(content),
        }

    return templates.TemplateResponse("wiki_detail.html", {
        "request": request,
        "kb": {"slug": slug, "name": slug},
        "wiki_files": wiki_files,
        "source_docs": sources,
        "active_doc": active,
        "active_page": "home",
    })


# ── Review (Git branches) ────────────────────────────────────


@app.get("/review", response_class=HTMLResponse)
async def review_list(request: Request):
    """List all ingest/reingest branches pending review."""
    result = _git("branch", "-a")
    branches = []
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            name = line.strip().lstrip("*").strip()
            if name.startswith("remotes/"):
                continue
            if name.startswith("ingest/") or name.startswith("reingest/"):
                # Get commit message
                msg_result = _git("log", "--oneline", "-1", name)
                msg = msg_result.stdout.strip() if (msg_result and msg_result.returncode == 0) else ""
                # Count changed files
                diff_result = _git("diff", "--stat", f"master...{name}")
                stat = diff_result.stdout.strip().split("\n")[-1] if (diff_result and diff_result.returncode == 0) else ""
                branches.append({
                    "name": name,
                    "message": msg,
                    "stat": stat,
                })

    return templates.TemplateResponse("review.html", {
        "request": request,
        "branches": branches,
        "active_page": "review",
    })


@app.get("/review/{branch:path}", response_class=HTMLResponse)
async def review_detail(request: Request, branch: str):
    """Show diff for a review branch."""
    # Get commit message
    msg_result = _git("log", "--oneline", "-1", branch)
    msg = msg_result.stdout.strip() if (msg_result and msg_result.returncode == 0) else "(no message)"

    # Get diff against master
    diff_result = _git("diff", f"master...{branch}")
    diff_text = diff_result.stdout if (diff_result and diff_result.returncode == 0) else "(diff failed)"

    # Also try to show the diff stat
    stat_result = _git("diff", "--stat", f"master...{branch}")
    stat_text = stat_result.stdout if (stat_result and stat_result.returncode == 0) else ""

    return templates.TemplateResponse("review_detail.html", {
        "request": request,
        "branch": branch,
        "message": msg,
        "stat": stat_text,
        "diff": diff_text,
        "active_page": "review",
    })


@app.post("/review/{branch:path}/approve")
async def review_approve(branch: str):
    """Approve: merge the branch into master."""
    r = _git("checkout", "master")
    if not r or r.returncode != 0:
        err = r.stderr if r else "git not available"
        return {"ok": False, "error": f"checkout master failed: {err}"}

    r = _git("merge", branch)
    if not r or r.returncode != 0:
        _git("merge", "--abort")
        _git("checkout", "master")
        err = r.stderr if r else "git not available"
        return {"ok": False, "error": f"merge failed: {err}"}

    _git("branch", "-d", branch)
    return {"ok": True, "message": f"Merged {branch} into master"}


@app.post("/review/{branch:path}/reject")
async def review_reject(branch: str):
    """Reject: delete the branch without merging."""
    r = _git("branch", "-D", branch)
    if not r or r.returncode != 0:
        err = r.stderr if r else "git not available"
        return {"ok": False, "error": f"delete failed: {err}"}
    return {"ok": True, "message": f"Deleted {branch}"}


# ── Settings ─────────────────────────────────────────────────


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "wiki_root": str(WIKI_ROOT),
    })
