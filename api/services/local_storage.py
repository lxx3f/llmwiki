import asyncio
import json
import logging
import os
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


class LocalStorageService:
    def __init__(self):
        self._root = Path(settings.STORAGE_ROOT).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        # Sanitize key to prevent path traversal
        safe_key = key.replace("\\", "/").lstrip("/")
        return (self._root / safe_key).resolve()

    def _check_path(self, path: Path):
        if not str(path).startswith(str(self._root)):
            raise ValueError(f"Path traversal denied: {path}")

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        file_path = self._resolve_path(key)
        self._check_path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(file_path.write_bytes, data)
        logger.debug("Uploaded: %s (%d bytes)", key, len(data))

    async def upload_file(self, key: str, file_path: str, content_type: str = "application/octet-stream"):
        data = await asyncio.to_thread(Path(file_path).read_bytes)
        await self.upload_bytes(key, data, content_type)

    async def generate_presigned_get(self, key: str, expires_in: int = 3600) -> str:
        """Return a local file URL (no real presigning needed for local storage)."""
        return f"{settings.API_URL}/files/{key}"

    async def generate_presigned_put(self, key: str, content_type: str = "application/pdf", expires_in: int = 3600) -> str:
        """Not used locally but kept for API compatibility."""
        return f"{settings.API_URL}/files/{key}"

    async def download_bytes(self, key: str) -> bytes:
        file_path = self._resolve_path(key)
        self._check_path(file_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {key}")
        return await asyncio.to_thread(file_path.read_bytes)

    async def download_to_file(self, key: str, file_path: str):
        data = await self.download_bytes(key)
        await asyncio.to_thread(Path(file_path).write_bytes, data)

    async def download_json(self, key: str) -> dict:
        body = await self.download_bytes(key)
        return json.loads(body)

    async def delete(self, key: str):
        """Remove a file from local storage."""
        file_path = self._resolve_path(key)
        self._check_path(file_path)
        if file_path.is_file():
            await asyncio.to_thread(file_path.unlink)
