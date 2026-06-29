from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from deps import get_user_id

router = APIRouter(prefix="/v1/extractions", tags=["extractions"])


class ExtractionOut(BaseModel):
    id: UUID
    document_id: UUID
    status: str
    proposed_content: str | None = None
    proposed_tags: list[str] | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class ReviewBody(BaseModel):
    proposed_content: str | None = None
    proposed_tags: list[str] | None = None


@router.get("", response_model=list[ExtractionOut])
async def list_extraction_tasks(
    request: Request,
    status: str | None = Query(None),
    kb_id: UUID | None = Query(None),
):
    pool = request.app.state.pool

    conditions = ["1=1"]
    params = []
    idx = 1

    if status:
        conditions.append(f"et.status = ${idx}")
        params.append(status)
        idx += 1
    if kb_id:
        conditions.append(f"d.knowledge_base_id = ${idx}")
        params.append(kb_id)
        idx += 1

    where = " AND ".join(conditions)
    rows = await pool.fetch(
        f"SELECT et.id, et.document_id, et.status, et.proposed_content, "
        f"et.proposed_tags, et.reviewed_at, et.created_at "
        f"FROM extraction_tasks et "
        f"JOIN documents d ON d.id = et.document_id "
        f"WHERE {where} ORDER BY et.created_at DESC",
        *params,
    )
    return [dict(r) for r in rows]


@router.post("", response_model=ExtractionOut, status_code=201)
async def create_extraction_task(
    doc_id: UUID,
    request: Request,
):
    """Create an extraction task and run AI extraction immediately."""
    pool = request.app.state.pool

    # Check document exists
    doc = await pool.fetchrow(
        "SELECT id, title, filename FROM documents WHERE id = $1", doc_id
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Create task
    row = await pool.fetchrow(
        "INSERT INTO extraction_tasks (document_id) VALUES ($1) "
        "RETURNING id, document_id, status, proposed_content, proposed_tags, reviewed_at, created_at",
        doc_id,
    )
    task_id = row["id"]

    # Run extraction in background
    from services.extraction import ExtractionService
    service = ExtractionService()
    import asyncio
    asyncio.create_task(_run_and_update(pool, service, doc_id, task_id))

    return dict(row)


async def _run_and_update(pool, service, doc_id, task_id):
    """Background task: run extraction and update the task row."""
    try:
        result = await service.extract_from_document(pool, str(doc_id), str(task_id))
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Extraction failed for task %s", task_id)


@router.post("/{task_id}/run", response_model=ExtractionOut)
async def run_extraction_task(task_id: UUID, request: Request):
    """Re-run AI extraction on an existing pending task."""
    pool = request.app.state.pool
    task = await pool.fetchrow(
        "SELECT id, document_id, status FROM extraction_tasks WHERE id = $1", task_id
    )
    if not task:
        raise HTTPException(status_code=404, detail="Extraction task not found")
    if task["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending tasks can be re-run")

    from services.extraction import ExtractionService
    service = ExtractionService()
    import asyncio
    asyncio.create_task(_run_and_update(pool, service, task["document_id"], task_id))

    # Return current state (will update when extraction completes)
    row = await pool.fetchrow(
        "SELECT id, document_id, status, proposed_content, proposed_tags, reviewed_at, created_at "
        "FROM extraction_tasks WHERE id = $1",
        task_id,
    )
    return dict(row)


@router.get("/{task_id}", response_model=ExtractionOut)
async def get_extraction_task(task_id: UUID, request: Request):
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "SELECT id, document_id, status, proposed_content, proposed_tags, reviewed_at, created_at "
        "FROM extraction_tasks WHERE id = $1",
        task_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Extraction task not found")
    return dict(row)


@router.post("/{task_id}/approve", status_code=204)
async def approve_extraction(
    task_id: UUID,
    body: ReviewBody | None = None,
    user_id: Annotated[str, Depends(get_user_id)] = None,
    request: Request = None,
):
    """Approve the extraction: write proposed content as a wiki page."""
    pool = request.app.state.pool
    task = await pool.fetchrow(
        "SELECT et.*, d.knowledge_base_id, d.filename, d.title "
        "FROM extraction_tasks et "
        "JOIN documents d ON d.id = et.document_id "
        "WHERE et.id = $1",
        task_id,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Extraction task not found")
    if task["status"] != "pending":
        raise HTTPException(status_code=400, detail="Task already reviewed")

    # Use form values if non-empty, otherwise fall back to stored AI content
    content = task["proposed_content"]
    tags = task["proposed_tags"] or []
    if body:
        if body.proposed_content:
            content = body.proposed_content
        if body.proposed_tags is not None:
            tags = body.proposed_tags
    title = task["title"] or task["filename"]
    wiki_filename = title.lower().replace(" ", "-") + ".md"

    conn = await pool.acquire()
    try:
        async with conn.transaction():
            doc_row = await conn.fetchrow(
                "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
                "file_type, status, content, tags) "
                "VALUES ($1, $2, $3, $4, '/wiki/', 'md', 'ready', $5, $6) "
                "RETURNING id",
                task["knowledge_base_id"], user_id, wiki_filename, title, content, tags,
            )
            await conn.execute(
                "UPDATE extraction_tasks SET status = 'approved', "
                "proposed_content = $1, proposed_tags = $2, reviewed_at = now() "
                "WHERE id = $3",
                content, tags, task_id,
            )
    finally:
        await pool.release(conn)

    # Auto-log
    import asyncio
    from services.log_service import log_extraction_approved
    asyncio.create_task(log_extraction_approved(
        pool, str(task["knowledge_base_id"]), user_id, title,
    ))


@router.post("/{task_id}/reject", status_code=204)
async def reject_extraction(
    task_id: UUID,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    task_info = await pool.fetchrow(
        "SELECT et.id, d.title, d.filename, d.knowledge_base_id "
        "FROM extraction_tasks et "
        "JOIN documents d ON d.id = et.document_id "
        "WHERE et.id = $1 AND et.status = 'pending'",
        task_id,
    )
    result = await pool.execute(
        "UPDATE extraction_tasks SET status = 'rejected', reviewed_at = now() "
        "WHERE id = $1 AND status = 'pending'",
        task_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Extraction task not found")

    # Auto-log
    if task_info:
        import asyncio
        from services.log_service import log_extraction_rejected
        asyncio.create_task(log_extraction_rejected(
            pool, str(task_info["knowledge_base_id"]), user_id,
            task_info["title"] or task_info["filename"],
        ))
