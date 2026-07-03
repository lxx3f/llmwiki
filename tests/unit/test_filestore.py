"""Unit tests for FileStore."""

import tempfile
import shutil
from pathlib import Path

import pytest

from services.filestore import FileStore, _slugify, _safe_filename


@pytest.fixture
def store():
    tmp = tempfile.mkdtemp(prefix="llmwiki_fs_test_")
    s = FileStore(tmp)
    s.ensure_dirs()
    yield s
    shutil.rmtree(tmp, ignore_errors=True)


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Test & Demo!") == "test-demo"

    def test_chinese(self):
        slug = _slugify("测试 知识库")
        assert "测试" in slug


class TestSafeFilename:
    def test_basic(self):
        assert _safe_filename("My File.pdf") == "my-file.pdf"

    def test_special_chars(self):
        name = _safe_filename("Hello: World! @2024")
        assert ":" not in name
        assert "!" not in name
        assert "@" not in name


class TestKB:

    def test_create_kb(self, store):
        kb = store.create_kb("My Wiki", "Test wiki")
        assert kb["name"] == "My Wiki"
        assert kb["slug"] == "my-wiki"
        assert kb["description"] == "Test wiki"

        # Check seed wiki pages
        wiki_files = list((store.root / "my-wiki" / "wiki").rglob("*.md"))
        assert len(wiki_files) == 3  # index, overview, log

    def test_create_kb_duplicate_fails(self, store):
        store.create_kb("Test")
        with pytest.raises(FileExistsError):
            store.create_kb("Test")

    def test_list_kbs(self, store):
        store.create_kb("A KB")
        store.create_kb("B KB")
        kbs = store.list_kbs()
        assert len(kbs) >= 2

    def test_get_kb(self, store):
        store.create_kb("Find Me")
        kb = store.get_kb("find-me")
        assert kb is not None
        assert kb["name"] == "Find Me"

    def test_get_kb_not_found(self, store):
        assert store.get_kb("nope") is None

    def test_delete_kb(self, store):
        store.create_kb("Delete Me")
        store.delete_kb("delete-me")
        assert store.get_kb("delete-me") is None


class TestWikiPages:

    def test_create_wiki_page(self, store):
        store.create_kb("KB")
        doc = store.create_wiki_page("kb", "/wiki/concepts/", "test.md",
                                     "# Test\n\nHello world", title="Test")
        assert doc["filename"] == "test.md"
        assert doc["path"] == "/wiki/concepts/"
        assert doc["file_type"] == "md"

        content = store.get_doc_content("kb", "wiki/concepts/test.md")
        assert "# Test" in content

    def test_update_wiki_content(self, store):
        store.create_kb("KB")
        store.create_wiki_page("kb", "/wiki/", "note.md", "Original")
        store.update_wiki_content("kb", "/wiki/", "note.md", "Updated")
        content = store.get_doc_content("kb", "wiki/note.md")
        assert content == "Updated"

    def test_delete_wiki_page(self, store):
        store.create_kb("KB")
        store.create_wiki_page("kb", "/wiki/", "trash-me.md", "blah")
        store.delete_wiki_page("kb", "/wiki/", "trash-me.md")
        assert store.get_doc_content("kb", "wiki/trash-me.md") is None


class TestSourceDocs:

    def test_create_source_doc(self, store):
        store.create_kb("KB")
        doc = store.create_source_doc("kb", "report.pdf", "pdf",
                                      source_bytes=b"%PDF-1.4 fake")
        assert doc["filename"] == "report.pdf"
        assert doc["file_type"] == "pdf"
        assert doc["document_number"] == 1
        assert doc["id"].startswith("sources/001__")

        # Source file exists
        source = store.get_source_path("kb", doc["id"])
        assert source is not None
        assert source.exists()

    def test_next_doc_number(self, store):
        store.create_kb("KB")
        assert store.next_doc_number("kb") == 1
        store.create_source_doc("kb", "first.pdf", "pdf", source_bytes=b"a")
        assert store.next_doc_number("kb") == 2

    def test_delete_source(self, store):
        store.create_kb("KB")
        doc = store.create_source_doc("kb", "tmp.pdf", "pdf", source_bytes=b"x")
        store.delete_source("kb", doc["id"])
        # After delete, get_doc returns None
        retrieved = store.get_doc("kb", doc["id"])
        assert retrieved is None or retrieved.get("archived")


class TestUsers:

    def test_get_or_create_user(self, store):
        user = store.get_or_create_user()
        assert "id" in user
        assert user["email"] == "local@llmwiki"

    def test_get_user(self, store):
        user = store.get_user()
        assert user is not None


class TestExtractionTasks:

    def test_crud(self, store):
        task = store.create_extraction_task("kb", "sources/001__test")
        assert task["status"] == "pending"
        assert task["kb_slug"] == "kb"

        tasks = store.list_extraction_tasks("kb")
        assert len(tasks) >= 1

        store.update_extraction_task(task["id"], status="approved")
        updated = store.get_extraction_task(task["id"])
        assert updated["status"] == "approved"
