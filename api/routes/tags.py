from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from deps import get_user_id

router = APIRouter(prefix="/v1/tags", tags=["tags"])


class CreateTag(BaseModel):
    name: str
    color: str | None = None


class UpdateTag(BaseModel):
    name: str | None = None
    color: str | None = None


class TagOut(BaseModel):
    id: UUID
    name: str
    color: str | None = None
    created_at: datetime


class DocumentTagOp(BaseModel):
    tag_id: UUID


# ── Tag CRUD ──

@router.get("", response_model=list[TagOut])
async def list_tags(request: Request):
    pool = request.app.state.pool
    rows = await pool.fetch("SELECT id, name, color, created_at FROM tags ORDER BY name")
    return [dict(r) for r in rows]


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(
    body: CreateTag,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    try:
        row = await pool.fetchrow(
            "INSERT INTO tags (name, color) VALUES ($1, $2) "
            "RETURNING id, name, color, created_at",
            body.name.strip(), body.color,
        )
    except Exception:
        raise HTTPException(status_code=409, detail="Tag already exists")
    return dict(row)


@router.put("/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: UUID,
    body: UpdateTag,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    updates = []
    params = []
    idx = 1
    if body.name is not None:
        updates.append(f"name = ${idx}")
        params.append(body.name.strip())
        idx += 1
    if body.color is not None:
        updates.append(f"color = ${idx}")
        params.append(body.color)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(tag_id)
    row = await pool.fetchrow(
        f"UPDATE tags SET {', '.join(updates)} WHERE id = ${idx} "
        "RETURNING id, name, color, created_at",
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    return dict(row)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: UUID,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    result = await pool.execute("DELETE FROM tags WHERE id = $1", tag_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Tag not found")


# ── Document-tag associations ──

@router.get("/documents/{doc_id}", response_model=list[TagOut])
async def get_document_tags(doc_id: UUID, request: Request):
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT t.id, t.name, t.color, t.created_at "
        "FROM tags t JOIN document_tags dt ON dt.tag_id = t.id "
        "WHERE dt.document_id = $1 ORDER BY t.name",
        doc_id,
    )
    return [dict(r) for r in rows]


@router.post("/documents/{doc_id}", response_model=list[TagOut])
async def add_document_tags(
    doc_id: UUID,
    body: DocumentTagOp,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    try:
        await pool.execute(
            "INSERT INTO document_tags (document_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            doc_id, body.tag_id,
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Document or tag not found")
    return await get_document_tags_inner(pool, doc_id)


@router.delete("/documents/{doc_id}/{tag_id}", status_code=204)
async def remove_document_tag(
    doc_id: UUID,
    tag_id: UUID,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    await pool.execute(
        "DELETE FROM document_tags WHERE document_id = $1 AND tag_id = $2",
        doc_id, tag_id,
    )


# ── Browse by tag ──

@router.get("/{tag_id}/documents")
async def list_documents_by_tag(tag_id: UUID, request: Request):
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT d.id, d.knowledge_base_id, d.filename, d.title, d.file_type, "
        "d.status, d.path, d.tags, d.archived, d.created_at, d.updated_at "
        "FROM documents d JOIN document_tags dt ON dt.document_id = d.id "
        "WHERE dt.tag_id = $1 AND NOT d.archived "
        "ORDER BY d.updated_at DESC",
        tag_id,
    )
    return [dict(r) for r in rows]


async def get_document_tags_inner(pool, doc_id: UUID):
    rows = await pool.fetch(
        "SELECT t.id, t.name, t.color, t.created_at "
        "FROM tags t JOIN document_tags dt ON dt.tag_id = t.id "
        "WHERE dt.document_id = $1 ORDER BY t.name",
        doc_id,
    )
    return [dict(r) for r in rows]
