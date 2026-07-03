"""Integration test fixtures — file-system backed."""

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from services.filestore import FileStore

API_DIR = Path(__file__).parent.parent.parent / "api"


@contextmanager
def _in_api_dir():
    old = os.getcwd()
    os.chdir(API_DIR)
    try:
        yield old
    finally:
        os.chdir(old)


@pytest.fixture
def store():
    """Create a temporary FileStore for testing."""
    tmp = tempfile.mkdtemp(prefix="llmwiki_test_")
    s = FileStore(tmp)
    s.ensure_dirs()
    yield s
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
async def client(store):
    """Async HTTP client for testing the FastAPI app."""
    with _in_api_dir():
        from main import app

    app.state.store = store
    app.state.ocr_service = None
    app.state.effective_user_id = store.get_or_create_user()["id"]

    # Seed a test KB
    store.create_kb("Test KB", "A test knowledge base")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
