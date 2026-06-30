import asyncio
import logging
import os
from contextlib import asynccontextmanager

# ── Fix broken SSL_CERT_FILE on conda/Windows ──
_ssl_cert = os.environ.get("SSL_CERT_FILE", "")
if not _ssl_cert or not os.path.isfile(_ssl_cert):
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass  # certifi not available, leave as-is

import asyncpg
import logfire
import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=True,
        traces_sample_rate=0.1,
        environment=settings.STAGE,
    )

if settings.LOGFIRE_TOKEN:
    logfire.configure(token=settings.LOGFIRE_TOKEN, service_name="llmwiki-api")
    logfire.instrument_asyncpg()

from routes.health import router as health_router
from routes.knowledge_bases import router as knowledge_bases_router
from routes.documents import router as documents_router
from routes.me import router as me_router
from routes.tags import router as tags_router
from routes.extraction import router as extraction_router
from routes.files import router as files_router
from infra.tus import router as tus_router, cleanup_stale_uploads


async def _recover_stuck_documents(pool: asyncpg.Pool, ocr_service):
    rows = await pool.fetch(
        "SELECT id::text, user_id::text FROM documents "
        "WHERE status IN ('pending', 'processing') AND NOT archived"
    )
    for row in rows:
        logger.info("Recovering stuck document %s", row["id"][:8])
        asyncio.create_task(ocr_service.process_document(row["id"], row["user_id"]))


async def _ensure_single_user(pool: asyncpg.Pool) -> str:
    """Ensure the single user row exists in the users table. Returns the effective user ID."""
    user_id = settings.SINGLE_USER_ID
    existing = await pool.fetchrow("SELECT id FROM users WHERE email = $1", "local@llmwiki")
    if existing:
        user_id = existing["id"]
        logger.info("Found existing single user: %s", user_id)
    else:
        await pool.execute(
            "INSERT INTO users (id, email, display_name, onboarded) "
            "VALUES ($1::uuid, $2, $2, true)",
            user_id, "local@llmwiki",
        )
        logger.info("Created single user: %s", user_id)
    return user_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=2, max_size=10)
    except (OSError, asyncpg.exceptions.PostgresError) as e:
        logger.critical(
            "❌ 无法连接到 PostgreSQL 数据库，请检查：\n"
            "  1. Docker 容器是否已启动？运行: docker compose up -d\n"
            "  2. DATABASE_URL 是否正确？当前: %s\n"
            "  3. 端口 5432 是否被占用？运行: docker ps\n"
            "  原始错误: %s",
            settings.DATABASE_URL, e,
        )
        raise SystemExit(1) from e

    app.state.pool = pool

    # Ensure single user exists
    try:
        app.state.effective_user_id = await _ensure_single_user(pool)
    except Exception as e:
        logger.critical(
            "❌ 初始化用户数据失败: %s\n请检查数据库迁移是否已执行。", e
        )
        await pool.close()
        raise SystemExit(1) from e

    # Local storage (always available)
    from services.local_storage import LocalStorageService
    storage = LocalStorageService()
    app.state.storage = storage

    # OCR service (requires converter if processing office docs)
    ocr_service = None
    from services.ocr import OCRService
    ocr_service = OCRService(storage, pool)
    app.state.ocr_service = ocr_service

    cleanup_task = asyncio.create_task(cleanup_stale_uploads())

    if ocr_service:
        await _recover_stuck_documents(pool, ocr_service)

    yield

    cleanup_task.cancel()
    await pool.close()


app = FastAPI(title="LLM Wiki API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Location", "Upload-Offset", "Upload-Length",
        "Tus-Resumable", "Tus-Version", "Tus-Max-Size", "Tus-Extension",
        "X-Document-Id",
    ],
)

if settings.LOGFIRE_TOKEN:
    logfire.instrument_fastapi(app)

# API routes
app.include_router(health_router)
app.include_router(knowledge_bases_router)
app.include_router(documents_router)
app.include_router(me_router)
app.include_router(tags_router)
app.include_router(extraction_router)
app.include_router(files_router)
app.include_router(tus_router)

# Static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Frontend routes (Jinja2 templates) ──

templates = Jinja2Templates(directory="templates")


async def _get_kb_list(pool):
    rows = await pool.fetch(
        "SELECT kb.id, kb.user_id, kb.name, kb.slug, kb.description, kb.created_at, kb.updated_at, "
        "  (SELECT COUNT(*) FROM documents d "
        "   WHERE d.knowledge_base_id = kb.id AND d.path NOT LIKE '/wiki/%%' AND NOT d.archived) AS source_count, "
        "  (SELECT COUNT(*) FROM documents d "
        "   WHERE d.knowledge_base_id = kb.id AND d.path LIKE '/wiki/%%' AND NOT d.archived) AS wiki_page_count "
        "FROM knowledge_bases kb ORDER BY kb.updated_at DESC"
    )
    return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    kbs = await _get_kb_list(request.app.state.pool)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "kbs": kbs,
        "active_page": "home",
    })


@app.get("/wikis/{slug}", response_class=HTMLResponse)
async def wiki_detail_page(request: Request, slug: str, doc: str = None, page: str = None):
    pool = request.app.state.pool
    kb = await pool.fetchrow(
        "SELECT id, user_id, name, slug FROM knowledge_bases WHERE slug = $1", slug
    )
    if not kb:
        return HTMLResponse("Knowledge base not found", status_code=404)

    kb = dict(kb)

    # Get documents list
    all_docs = await pool.fetch(
        "SELECT id, filename, title, path, file_type, tags, status "
        "FROM documents WHERE knowledge_base_id = $1 AND NOT archived "
        "ORDER BY path, filename",
        kb["id"],
    )
    all_docs = [dict(d) for d in all_docs]
    wiki_docs = [d for d in all_docs if d["path"].startswith("/wiki/")]
    source_docs = [d for d in all_docs if not d["path"].startswith("/wiki/")]

    # Active document
    active_doc = None
    if doc:
        active_doc = await pool.fetchrow(
            "SELECT id, filename, title, path, file_type, tags, content, page_count "
            "FROM documents WHERE id = $1 AND NOT archived", doc
        )
        active_doc = dict(active_doc) if active_doc else None
    elif page:
        # page param looks like "/wiki/concepts/something.md"
        p = page if page.startswith("/") else "/" + page
        if "/" in p:
            dpath = "/" + p[1:].rsplit("/", 1)[0] + "/" if len(p.split("/")) > 2 else "/wiki/"
            fname = p.rsplit("/", 1)[-1]
        else:
            dpath = "/wiki/"
            fname = p
        active_doc = await pool.fetchrow(
            "SELECT id, filename, title, path, file_type, tags, content, page_count "
            "FROM documents WHERE knowledge_base_id = $1 AND path = $2 AND filename = $3 AND NOT archived",
            kb["id"], dpath, fname,
        )
        active_doc = dict(active_doc) if active_doc else None

    # Markdown rendering (server-side)
    if active_doc and active_doc.get("content"):
        import mistune
        md = mistune.create_markdown(plugins=[
            "table", "strikethrough", "footnotes", "task_lists", "url",
        ])
        active_doc["content"] = md(active_doc["content"])

    return templates.TemplateResponse("wiki_detail.html", {
        "request": request,
        "kb": kb,
        "wiki_docs": wiki_docs,
        "source_docs": source_docs,
        "active_doc": active_doc,
        "active_page": "home",
    })


@app.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request):
    return templates.TemplateResponse("tags.html", {
        "request": request,
        "active_page": "tags",
    })


@app.get("/extractions", response_class=HTMLResponse)
async def extractions_page(request: Request):
    return templates.TemplateResponse("extraction.html", {
        "request": request,
        "active_page": "extractions",
    })


@app.get("/extractions/{task_id}", response_class=HTMLResponse)
async def extraction_review_page(request: Request, task_id: str):
    pool = request.app.state.pool
    task = await pool.fetchrow(
        "SELECT id, document_id, status, proposed_content, proposed_tags, reviewed_at, created_at "
        "FROM extraction_tasks WHERE id = $1", task_id
    )
    return templates.TemplateResponse("extraction_review.html", {
        "request": request,
        "task": dict(task) if task else None,
        "active_page": "extractions",
    })


@app.get("/qa", response_class=HTMLResponse)
async def qa_page(request: Request):
    return templates.TemplateResponse("qa.html", {
        "request": request,
        "active_page": "qa",
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "mcp_url": settings.MCP_URL,
        "storage_root": settings.STORAGE_ROOT,
        "ollama_url": settings.OLLAMA_URL,
        "user_id": request.app.state.effective_user_id,
    })


@app.get("/v1/search/chunks")
async def search_chunks(request: Request, kb_id: str, q: str, limit: int = 10):
    """Simple chunk search endpoint for the QA page."""
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT dc.content, dc.page, d.filename, d.title "
        "FROM document_chunks dc "
        "JOIN documents d ON dc.document_id = d.id "
        "WHERE dc.knowledge_base_id = $1 "
        "  AND dc.content &@~ $2 "
        "  AND NOT d.archived "
        "ORDER BY pgroonga_score(dc.tableoid, dc.ctid) DESC "
        "LIMIT $3",
        kb_id, q, limit,
    )
    return [dict(r) for r in rows]
