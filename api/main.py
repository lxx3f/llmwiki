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

from config import settings

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────

WIKI_ROOT = Path(settings.WIKI_ROOT)
if not WIKI_ROOT.is_absolute():
    WIKI_ROOT = (Path(__file__).parent.parent / WIKI_ROOT).resolve()


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


@app.get("/wiki/index")
async def global_index(request: Request, kb: str = Query(None)):
    """Top-level: full wiki index across the default KB."""
    return _render_special_page(request, kb or "", "index")


@app.get("/wiki/overview")
async def global_overview(request: Request, kb: str = Query(None)):
    """Top-level: wiki overview / knowledge map."""
    return _render_special_page(request, kb or "", "overview")


@app.get("/wiki/log")
async def global_log(request: Request, kb: str = Query(None)):
    """Top-level: operation log (append-only timeline)."""
    return _render_special_page(request, kb or "", "log")


# NOTE: This catch-all /wiki/{slug} route is declared AFTER the literal
# /wiki/{index,overview,log} routes above because Starlette matches in
# declaration order — the catch-all would otherwise swallow "index" etc.
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

    # Active page content (wiki markdown)
    # Skip when ?source= is present — source viewer takes over the content pane.
    active = None
    if not request.query_params.get("source"):
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
        "active_source": _resolve_source_active(kb_dir / "sources", request),
        "active_page": "home",
    })


def _resolve_source_active(sources_dir: Path, request: Request) -> dict | None:
    """Parse ?source= and ?file= query params into a preview descriptor.

    Returns a dict with doc_id, file_path, and view_mode (one of
    "iframe", "image", "markdown", "text"), or None if no preview requested.
    """
    doc_id = request.query_params.get("source")
    rel_file = request.query_params.get("file")
    if not doc_id or not rel_file:
        return None

    target = (sources_dir / doc_id / rel_file).resolve()
    doc_root = (sources_dir / doc_id).resolve()
    # Path-traversal guard: target must live under doc_root
    if not str(target).startswith(str(doc_root)) or not target.is_file():
        return None

    ext = target.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp"}:
        view_mode = "image"
    elif ext in {".pdf"}:
        view_mode = "iframe"
    elif ext in {".md", ".markdown"}:
        view_mode = "markdown"
    elif ext in {".txt", ".csv", ".log", ".json", ".py", ".js", ".html", ".css", ".xml", ".yaml", ".yml"}:
        view_mode = "text"
    else:
        view_mode = "iframe"  # unknown binary — let browser try

    return {
        "doc_id": doc_id,
        "file_path": rel_file,
        "file_name": target.name,
        "view_mode": view_mode,
        "url": f"/wiki/{request.path_params.get('slug', '')}/source/{doc_id}/{rel_file}",
    }


@app.get("/wiki/{slug}/source/{doc_id}/{file_path:path}")
async def source_file(slug: str, doc_id: str, file_path: str):
    """Stream a raw source file to the browser.

    The browser picks the viewer by Content-Type (PDF, images, etc).
    Path-traversal is blocked via resolve() + startswith() check.
    """
    kb_dir = WIKI_ROOT / slug
    doc_root = (kb_dir / "sources" / doc_id).resolve()
    target = (doc_root / file_path).resolve()
    if not str(target).startswith(str(doc_root)) or not target.is_file():
        return HTMLResponse("forbidden", status_code=403)
    return FileResponse(target)


def _default_kb_slug() -> str:
    """Pick the first knowledge base directory that contains a wiki/ folder."""
    if WIKI_ROOT.exists():
        for d in sorted(WIKI_ROOT.iterdir()):
            if d.is_dir() and (d / "wiki").is_dir():
                return d.name
    return ""


def _render_special_page(request: Request, slug: str, page: str) -> HTMLResponse:
    """Render a top-level wiki page (index/log/overview) using mistune.

    If ?kb= is given, render that KB's page; otherwise use the first KB.
    """
    import mistune

    if slug:
        kb_slug = slug
    else:
        kb_slug = _default_kb_slug()
        if not kb_slug:
            return HTMLResponse("No knowledge base found", status_code=404)

    md_path = WIKI_ROOT / kb_slug / "wiki" / f"{page}.md"
    if not md_path.is_file():
        return HTMLResponse(f"{page}.md not found in {kb_slug}", status_code=404)

    content = md_path.read_text(encoding="utf-8", errors="replace")
    md = mistune.create_markdown(plugins=[
        "table", "strikethrough", "footnotes", "task_lists", "url",
    ])
    return templates.TemplateResponse("wiki_detail.html", {
        "request": request,
        "kb": {"slug": kb_slug, "name": kb_slug},
        "wiki_files": [],
        "source_docs": [],
        "active_doc": {
            "path": f"{page}.md",
            "name": page,
            "content": md(content),
        },
        "active_source": None,
        "active_page": page,
    })


@app.get("/wiki/index")
async def global_index(request: Request, kb: str = Query(None)):
    """Top-level: full wiki index across the default KB."""
    return _render_special_page(request, kb or "", "index")


@app.get("/wiki/overview")
async def global_overview(request: Request, kb: str = Query(None)):
    """Top-level: wiki overview / knowledge map."""
    return _render_special_page(request, kb or "", "overview")


@app.get("/wiki/log")
async def global_log(request: Request, kb: str = Query(None)):
    """Top-level: operation log (append-only timeline)."""
    return _render_special_page(request, kb or "", "log")

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
    """Approve: merge the branch into master, then redirect to review list.

    On conflict, abort cleanly and return a structured error so the UI can
    surface the real cause (conflict files, git error message).
    """
    r = _git("checkout", "master")
    if not r or r.returncode != 0:
        return {"ok": False, "error": f"checkout master failed: {(r.stderr or '').strip() or 'git not available'}"}

    r = _git("merge", branch)
    if not r or r.returncode != 0:
        # Detect conflict files from index
        conflicted = _git("diff", "--name-only", "--diff-filter=U")
        conflict_files = conflicted.stdout.strip().splitlines() if (conflicted and conflicted.returncode == 0) else []
        _git("merge", "--abort")
        _git("checkout", "master")
        err_msg = (r.stderr or "").strip()
        return {
            "ok": False,
            "error": err_msg or "merge failed",
            "conflicts": conflict_files,
            "hint": "请在终端手动解决冲突后再次合并" if conflict_files else None,
        }

    _git("branch", "-d", branch)
    return RedirectResponse(url="/review", status_code=303)


@app.post("/review/{branch:path}/reject")
async def review_reject(branch: str):
    """Reject: delete the branch without merging, then redirect to review list."""
    r = _git("branch", "-D", branch)
    if not r or r.returncode != 0:
        return {"ok": False, "error": f"delete failed: {r.stderr if r else 'git not available'}"}
    return RedirectResponse(url="/review", status_code=303)


# ── Agent monitor ────────────────────────────────────────────

from agent_monitor import (  # noqa: E402
    is_stale, list_kbs, parse_log_level, pending_docs,
    read_errors_tail, read_log_tail, read_state, recent_ingests,
)


@app.get("/agent", response_class=HTMLResponse)
async def agent_dashboard(request: Request):
    """Agent monitoring dashboard. Auto-refreshes via HTMX every 5s."""
    state = read_state()
    kbs = list_kbs()
    pending = pending_docs("main") if kbs else []
    return templates.TemplateResponse("agent.html", {
        "request": request,
        "active_page": "agent",
        "state": state,
        "stale": is_stale(state),
        "kbs": kbs,
        "pending": pending,
    })


@app.get("/v1/agent/status")
async def agent_status_json():
    """JSON status for SPA/MCP consumers."""
    state = read_state()
    return {
        "state": state,
        "stale": is_stale(state),
        "kbs": list_kbs(),
        "pending": pending_docs("main"),
        "recent_ingests": recent_ingests(10),
    }


@app.get("/agent/log")
async def agent_log_partial(request: Request, tail: int = 30, level: str = "all"):
    """HTMX partial: last N log lines from main log, formatted as a <pre> block.

    level: "all" | "warn" | "error" — filters by minimum severity.
    """
    lines = read_log_tail(tail, level_filter=level)
    return templates.TemplateResponse("agent_log_partial.html", {
        "request": request,
        "lines": lines,
        "parse_level": parse_log_level,
    })


@app.get("/agent/errors")
async def agent_errors_partial(request: Request, tail: int = 30):
    """HTMX partial: last N lines from the errors-only log (WARNING+ERROR)."""
    lines = read_errors_tail(tail)
    return templates.TemplateResponse("agent_log_partial.html", {
        "request": request,
        "lines": lines,
        "parse_level": parse_log_level,
    })


@app.get("/agent/history")
async def agent_history_partial(request: Request, limit: int = 10):
    """HTMX partial: recent ingest commits from git log."""
    items = recent_ingests(limit)
    return templates.TemplateResponse("agent_history_partial.html", {
        "request": request,
        "items": items,
    })


# ── Settings ─────────────────────────────────────────────────


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "wiki_root": str(WIKI_ROOT),
    })
