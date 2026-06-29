import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from config import settings

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{doc_id}/{subpath:path}")
async def serve_file(doc_id: str, subpath: str, request: Request):
    """Serve a locally stored file."""
    storage = getattr(request.app.state, "storage", None)
    if not storage:
        raise HTTPException(status_code=501, detail="Storage not configured")

    file_key = f"{doc_id}/{subpath}"
    file_path = storage._resolve_path(file_key)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type from extension
    ext = subpath.rsplit(".", 1)[-1].lower() if "." in subpath else ""
    media_type_map = {
        "pdf": "application/pdf",
        "html": "text/html",
        "htm": "text/html",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "json": "application/json",
        "xml": "application/xml",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "md": "text/markdown",
    }
    media_type = media_type_map.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type)
