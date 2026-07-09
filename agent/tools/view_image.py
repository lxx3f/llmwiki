"""View image tool — read image file and return base64 for multi-modal models."""

import base64
import logging
from pathlib import Path

from config import WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Read an image file and return it for visual analysis.
Returns base64-encoded image data that multi-modal models can process.
Use for: viewing screenshots, diagrams, photos in source documents.
If the model does not support images, returns a description instead.
Supported formats: png, jpg/jpeg, webp, gif, bmp."""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Image file path relative to WIKI_ROOT, e.g. 'my-kb/sources/001__paper/photo.png'",
        },
    },
    "required": ["path"],
}

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def execute(path: str, *, supports_images: bool = True) -> dict:
    """Read an image and return base64 data (or a description if images unsupported)."""
    full_path = WIKI_ROOT / path

    try:
        full_path.resolve().relative_to(WIKI_ROOT.resolve())
    except ValueError:
        return {"error": f"Path '{path}' escapes WIKI_ROOT — rejected"}

    if not full_path.exists():
        return {"error": f"File not found: {path}"}

    ext = full_path.suffix.lower()
    mime = MIME_MAP.get(ext)
    if not mime:
        return {"error": f"Unsupported image format: {ext}. Supported: {', '.join(MIME_MAP.keys())}"}

    size = full_path.stat().st_size
    data = full_path.read_bytes()

    if not supports_images:
        return {
            "note": (
                f"This model does not support visual input. "
                f"Image at '{path}' — {mime}, {_format_size(size)}. "
                f"Describe the image based on its filename and context."
            ),
            "path": path,
            "mime_type": mime,
            "size": size,
        }

    b64 = base64.b64encode(data).decode("ascii")
    logger.info("read image: %s (%s)", path, _format_size(size))

    return {
        "path": path,
        "mime_type": mime,
        "size": size,
        "base64": b64,
    }


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
