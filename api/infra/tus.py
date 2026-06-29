import json
import time
import asyncio
import logging
from uuid import uuid4
from pathlib import Path
from base64 import b64decode
from dataclasses import dataclass, field

from fastapi import APIRouter, Request, HTTPException, Response

logger = logging.getLogger(__name__)


def _append_file(path: Path, data: bytes):
    with open(path, "ab") as f:
        f.write(data)

TUS_VERSION = "1.0.0"
MAX_SIZE = 104_857_600  # 100 MB
UPLOAD_DIR = Path("/tmp/llmwiki_tus_uploads")
STALE_SECONDS = 3600

ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".pptx": "pptx", ".ppt": "ppt",
    ".docx": "docx", ".doc": "doc",
    ".png": "png", ".jpg": "jpg", ".jpeg": "jpeg",
    ".webp": "webp", ".gif": "gif",
    ".xlsx": "xlsx", ".xls": "xls", ".csv": "csv",
    ".html": "html", ".htm": "html",
    ".md": "md", ".txt": "txt", ".markdown": "md",
}
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel", "csv": "text/csv",
    "html": "text/html", "htm": "text/html",
    "md": "text/markdown", "txt": "text/plain", "markdown": "text/markdown",
}

router = APIRouter(prefix="/v1/uploads", tags=["tus"])


@dataclass
class TusUpload:
    upload_id: str
    upload_length: int
    upload_offset: int
    filename: str
    knowledge_base_id: str
    temp_path: Path
    last_activity: float = field(default_factory=time.time)


_uploads: dict[str, TusUpload] = {}


def _check_tus_version(request: Request):
    version = request.headers.get("Tus-Resumable")
    if version != TUS_VERSION:
        raise HTTPException(status_code=412, detail=f"Unsupported Tus-Resumable version (expected {TUS_VERSION})")


def _parse_metadata(header: str) -> dict[str, str]:
    result = {}
    if not header:
        return result
    for pair in header.split(","):
        pair = pair.strip()
        parts = pair.split(" ", 1)
        key = parts[0]
        if len(parts) > 1:
            try:
                value = b64decode(parts[1]).decode("utf-8")
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid base64 in Upload-Metadata key '{key}'")
        else:
            value = ""
        result[key] = value
    return result


def _tus_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Tus-Resumable": TUS_VERSION}
    if extra:
        headers.update(extra)
    return headers


def _get_upload(upload_id: str) -> TusUpload:
    upload = _uploads.get(upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload


async def _finalize(upload: TusUpload, app_state) -> str:
    document_id = str(uuid4())
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else "pdf"
    file_type = ALLOWED_EXTENSIONS.get(f".{ext}", ext)
    storage_key = f"{document_id}/source.{ext}"
    title = upload.filename.rsplit(".", 1)[0] if "." in upload.filename else upload.filename
    file_size = upload.upload_length

    storage = app_state.storage
    await storage.upload_file(storage_key, str(upload.temp_path), CONTENT_TYPES.get(ext, "application/octet-stream"))

    pool = app_state.pool
    user_id = app_state.effective_user_id
    try:
        await pool.execute(
            "INSERT INTO documents (id, knowledge_base_id, user_id, filename, path, title, "
            "file_type, file_size, status) "
            "VALUES ($1::uuid, $2::uuid, $3, $4, '/', $5, $6, $7, 'pending')",
            document_id,
            upload.knowledge_base_id,
            user_id,
            upload.filename,
            title,
            file_type,
            file_size,
        )
    finally:
        upload.temp_path.unlink(missing_ok=True)
        _uploads.pop(upload.upload_id, None)

    ocr_service = app_state.ocr_service
    if ocr_service:
        asyncio.create_task(ocr_service.process_document(document_id, user_id))

    # Auto-log: document uploaded
    try:
        from services.log_service import log_document_uploaded
        asyncio.create_task(log_document_uploaded(
            pool, upload.knowledge_base_id, user_id,
            upload.filename, document_id,
        ))
    except Exception:
        logger.exception("Failed to create log entry for upload")

    logger.info("TUS finalized: doc=%s file=%s", document_id[:8], upload.filename)
    return document_id


async def cleanup_stale_uploads():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [uid for uid, u in _uploads.items() if now - u.last_activity > STALE_SECONDS]
        for uid in stale:
            upload = _uploads.pop(uid, None)
            if upload:
                upload.temp_path.unlink(missing_ok=True)
                logger.info("Cleaned stale TUS upload: %s", uid)


@router.options("")
async def tus_options():
    return Response(
        status_code=204,
        headers=_tus_headers({
            "Tus-Version": TUS_VERSION,
            "Tus-Max-Size": str(MAX_SIZE),
            "Tus-Extension": "creation",
        }),
    )


@router.post("", status_code=201)
async def tus_create(request: Request):
    _check_tus_version(request)

    upload_length_str = request.headers.get("Upload-Length")
    if not upload_length_str:
        raise HTTPException(status_code=400, detail="Missing Upload-Length header")
    try:
        upload_length = int(upload_length_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Upload-Length")
    if upload_length > MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"Upload-Length exceeds maximum of {MAX_SIZE} bytes")

    meta_header = request.headers.get("Upload-Metadata", "")
    metadata = _parse_metadata(meta_header)
    logger.info("TUS create: meta_header=%r, parsed=%r", meta_header[:200], metadata)

    filename = metadata.get("filename", "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename in Upload-Metadata")

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )

    kb_id = metadata.get("knowledge_base_id", "").strip()
    if not kb_id:
        raise HTTPException(status_code=400, detail="Missing knowledge_base_id in Upload-Metadata")

    pool = request.app.state.pool
    try:
        import uuid as _uuid
        _uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid knowledge_base_id format")

    kb_exists = await pool.fetchval(
        "SELECT id FROM knowledge_bases WHERE id = $1::uuid",
        kb_id,
    )
    if not kb_exists:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = str(uuid4())
    temp_path = UPLOAD_DIR / upload_id
    temp_path.touch()

    upload = TusUpload(
        upload_id=upload_id,
        upload_length=upload_length,
        upload_offset=0,
        filename=filename,
        knowledge_base_id=kb_id,
        temp_path=temp_path,
    )
    _uploads[upload_id] = upload

    location = f"/v1/uploads/{upload_id}"
    return Response(status_code=201, headers=_tus_headers({"Location": location}))


@router.head("/{upload_id}")
async def tus_head(upload_id: str, request: Request):
    upload = _get_upload(upload_id)
    return Response(
        status_code=200,
        headers=_tus_headers({
            "Upload-Offset": str(upload.upload_offset),
            "Upload-Length": str(upload.upload_length),
            "Cache-Control": "no-store",
        }),
    )


@router.patch("/{upload_id}", status_code=204)
async def tus_patch(upload_id: str, request: Request):
    _check_tus_version(request)

    content_type = request.headers.get("Content-Type", "")
    if content_type != "application/offset+octet-stream":
        raise HTTPException(status_code=415, detail="Content-Type must be application/offset+octet-stream")

    upload = _get_upload(upload_id)

    offset_str = request.headers.get("Upload-Offset")
    if offset_str is None:
        raise HTTPException(status_code=400, detail="Missing Upload-Offset header")
    try:
        client_offset = int(offset_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Upload-Offset")

    if client_offset != upload.upload_offset:
        raise HTTPException(status_code=409, detail="Offset mismatch")

    FLUSH_SIZE = 1_048_576
    buf = bytearray()
    bytes_written = 0
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) >= FLUSH_SIZE:
            await asyncio.to_thread(_append_file, upload.temp_path, bytes(buf))
            bytes_written += len(buf)
            buf.clear()

    if buf:
        await asyncio.to_thread(_append_file, upload.temp_path, bytes(buf))
        bytes_written += len(buf)
    upload.upload_offset += bytes_written

    upload.last_activity = time.time()

    if upload.upload_offset > upload.upload_length:
        upload.temp_path.unlink(missing_ok=True)
        _uploads.pop(upload_id, None)
        raise HTTPException(status_code=400, detail="Upload exceeded declared length")

    headers = _tus_headers({"Upload-Offset": str(upload.upload_offset)})

    if upload.upload_offset == upload.upload_length:
        try:
            document_id = await _finalize(upload, request.app.state)
            headers["X-Document-Id"] = document_id
        except Exception:
            logger.exception("TUS finalization failed for upload %s", upload_id)
            raise HTTPException(status_code=500, detail="Finalization failed")

    return Response(status_code=204, headers=headers)
