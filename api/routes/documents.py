import json
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from config import settings
from deps import get_scoped_db, get_user_id
from scoped_db import ScopedDB
from services.chunker import chunk_text, store_chunks

router = APIRouter(tags=["documents"])

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.+?\n)---[ \t]*\n", re.DOTALL)

_DOC_COLUMNS = (
    "id, knowledge_base_id, user_id, filename, path, title, "
    "file_type, status, tags, date, metadata, error_message, "
    "version, document_number, archived, created_at, updated_at"
)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, content
    if not isinstance(meta, dict):
        return {}, content
    return meta, content[m.end():]


class CreateNote(BaseModel):
    filename: str
    path: str = "/"
    content: str = ""


class UpdateContent(BaseModel):
    content: str


class UpdateMetadata(BaseModel):
    filename: str | None = None
    path: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    date: str | None = None
    metadata: dict | None = None


class DocumentOut(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    user_id: UUID
    filename: str
    path: str
    title: str | None
    file_type: str
    status: str
    tags: list[str]
    date: str | None = None
    metadata: dict | None = None
    error_message: str | None = None
    version: int
    document_number: int | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class DocumentContent(BaseModel):
    id: UUID
    content: str | None
    version: int


class BulkDelete(BaseModel):
    ids: list[UUID]


# ── Read routes ──

@router.get("/v1/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
    path: str | None = Query(None),
):
    if path:
        rows = await db.fetch(
            f"SELECT {_DOC_COLUMNS} "
            "FROM documents WHERE knowledge_base_id = $1 AND archived = false AND path = $2 "
            "ORDER BY filename",
            kb_id, path,
        )
    else:
        rows = await db.fetch(
            f"SELECT {_DOC_COLUMNS} "
            "FROM documents WHERE knowledge_base_id = $1 AND archived = false "
            "ORDER BY filename",
            kb_id,
        )
    return rows


@router.get("/v1/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
):
    row = await db.fetchrow(
        f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = $1",
        doc_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.get("/v1/documents/{doc_id}/url")
async def get_document_url(
    doc_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
    request: Request,
):
    """Return a local file download URL for the document."""
    row = await db.fetchrow(
        "SELECT id, filename, file_type FROM documents WHERE id = $1",
        doc_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = request.app.state.storage
    ext = row["filename"].rsplit(".", 1)[-1].lower() if "." in row["filename"] else row["file_type"]
    office_types = {"pptx", "ppt", "docx", "doc"}
    html_types = {"html", "htm"}
    if ext in office_types:
        file_key = f"{row['id']}/converted.pdf"
    elif ext in html_types:
        file_key = f"{row['id']}/tagged.html"
    else:
        file_key = f"{row['id']}/source.{ext}"

    return {"url": f"{settings.API_URL}/files/{file_key}"}


@router.get("/v1/documents/{doc_id}/content", response_model=DocumentContent)
async def get_document_content(
    doc_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
):
    row = await db.fetchrow(
        "SELECT id, content, version FROM documents WHERE id = $1",
        doc_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


# ── Write routes ──

@router.post("/v1/knowledge-bases/{kb_id}/documents/note", response_model=DocumentOut, status_code=201)
async def create_note(
    kb_id: UUID,
    body: CreateNote,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    kb = await pool.fetchval(
        "SELECT id FROM knowledge_bases WHERE id = $1",
        kb_id,
    )
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    meta, _ = parse_frontmatter(body.content)

    if isinstance(meta.get("title"), str) and meta["title"].strip():
        title = meta["title"].strip()
    else:
        stem = body.filename.rsplit(".", 1)[0] if "." in body.filename else body.filename
        title = stem.replace("-", " ").replace("_", " ").strip().title()

    tags: list[str] = []
    if isinstance(meta.get("tags"), list):
        tags = [str(t) for t in meta["tags"] if t is not None]

    conn = await pool.acquire()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO documents (knowledge_base_id, user_id, filename, path, title, "
                "file_type, status, content, tags) "
                "VALUES ($1, $2, $3, $4, $5, 'md', 'ready', $6, $7) "
                f"RETURNING {_DOC_COLUMNS}",
                kb_id, user_id, body.filename, body.path, title, body.content, tags,
            )
            if body.content:
                chunks = chunk_text(body.content)
                await store_chunks(conn, str(row["id"]), user_id, str(kb_id), chunks)
    finally:
        await pool.release(conn)

    # Auto-log
    import asyncio
    from services.log_service import log_note_created
    asyncio.create_task(log_note_created(pool, str(kb_id), user_id, title, body.path))

    return dict(row)


@router.put("/v1/documents/{doc_id}/content", response_model=DocumentContent)
async def update_document_content(
    doc_id: UUID,
    body: UpdateContent,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    row = await pool.fetchrow(
        "UPDATE documents SET content = $1, version = version + 1, updated_at = now() "
        "WHERE id = $2 "
        "RETURNING id, content, version",
        body.content, doc_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    kb_id = await pool.fetchval(
        "SELECT knowledge_base_id::text FROM documents WHERE id = $1", doc_id,
    )
    if kb_id:
        chunks = chunk_text(body.content) if body.content else []
        await store_chunks(pool, str(doc_id), user_id, kb_id, chunks)

    # Auto-log
    import asyncio
    from services.log_service import log_content_updated
    doc_info = await pool.fetchrow(
        "SELECT title, filename, knowledge_base_id FROM documents WHERE id = $1", doc_id,
    )
    if doc_info:
        asyncio.create_task(log_content_updated(
            pool, str(doc_info["knowledge_base_id"]), user_id,
            doc_info["title"] or "", doc_info["filename"],
        ))

    return dict(row)


@router.patch("/v1/documents/{doc_id}", response_model=DocumentOut)
async def update_document_metadata(
    doc_id: UUID,
    body: UpdateMetadata,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    updates = []
    params = []
    idx = 1

    if body.filename is not None:
        updates.append(f"filename = ${idx}")
        params.append(body.filename)
        idx += 1
    if body.path is not None:
        updates.append(f"path = ${idx}")
        params.append(body.path)
        idx += 1
    if body.title is not None:
        updates.append(f"title = ${idx}")
        params.append(body.title)
        idx += 1
    if body.tags is not None:
        updates.append(f"tags = ${idx}")
        params.append(body.tags)
        idx += 1
    if body.date is not None:
        updates.append(f"date = ${idx}")
        params.append(body.date if body.date else None)
        idx += 1
    if body.metadata is not None:
        updates.append(f"metadata = ${idx}")
        params.append(json.dumps(body.metadata))
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = now()")
    params.append(doc_id)

    sql = (
        f"UPDATE documents SET {', '.join(updates)} "
        f"WHERE id = ${idx} "
        f"RETURNING {_DOC_COLUMNS}"
    )
    row = await pool.fetchrow(sql, *params)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@router.post("/v1/documents/bulk-delete", status_code=204)
async def bulk_delete_documents(
    body: BulkDelete,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    if not body.ids:
        return
    pool = request.app.state.pool

    # Fetch doc info for logging before archiving
    rows = await pool.fetch(
        "SELECT id, filename, title, knowledge_base_id FROM documents WHERE id = ANY($1::uuid[])",
        [str(i) for i in body.ids],
    )

    await pool.execute(
        "UPDATE documents SET archived = true, updated_at = now() "
        "WHERE id = ANY($1::uuid[])",
        [str(i) for i in body.ids],
    )

    if rows:
        import asyncio
        from services.log_service import log_document_deleted
        by_kb: dict = {}
        for r in rows:
            by_kb.setdefault(str(r["knowledge_base_id"]), []).append(r)
        for kb_id, docs in by_kb.items():
            first = docs[0]
            asyncio.create_task(log_document_deleted(
                pool, kb_id, user_id,
                first["title"] or first["filename"],
                count=len(docs),
            ))


@router.delete("/v1/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: UUID,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    doc_info = await pool.fetchrow(
        "SELECT filename, title, knowledge_base_id FROM documents WHERE id = $1", doc_id,
    )
    result = await pool.execute(
        "UPDATE documents SET archived = true, updated_at = now() "
        "WHERE id = $1",
        doc_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Document not found")

    # Auto-log
    if doc_info:
        import asyncio
        from services.log_service import log_document_deleted
        asyncio.create_task(log_document_deleted(
            pool, str(doc_info["knowledge_base_id"]), user_id,
            doc_info["title"] or doc_info["filename"],
        ))
