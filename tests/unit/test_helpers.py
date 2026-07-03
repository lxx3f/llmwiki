"""Unit tests for route helpers and utilities."""

from routes.documents import parse_frontmatter


class TestFrontmatterParsing:

    def test_valid_frontmatter(self):
        content = "---\ntitle: My Doc\ntags:\n  - research\n---\nBody text here."
        meta, body = parse_frontmatter(content)
        assert meta["title"] == "My Doc"
        assert meta["tags"] == ["research"]
        assert body == "Body text here."

    def test_no_frontmatter(self):
        content = "Just plain text."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_invalid_yaml_returns_empty(self):
        content = "---\n: invalid: yaml: [[\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta == {}

    def test_non_dict_yaml_returns_empty(self):
        content = "---\n- just a list\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content
