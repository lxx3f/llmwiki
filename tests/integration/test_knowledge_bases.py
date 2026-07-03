"""Integration tests for knowledge base CRUD (file-system backed)."""


class TestListKnowledgeBases:

    async def test_list_returns_seeded_kb(self, client):
        res = await client.get("/v1/knowledge-bases")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(kb["name"] == "Test KB" for kb in data)

    async def test_list_includes_counts(self, client):
        res = await client.get("/v1/knowledge-bases")
        assert res.status_code == 200
        for kb in res.json():
            assert "source_count" in kb
            assert "wiki_page_count" in kb
            # Seed KB has 3 wiki pages (index, overview, log)
            assert kb["wiki_page_count"] >= 0


class TestCreateKnowledgeBase:

    async def test_create_minimal(self, client):
        res = await client.post("/v1/knowledge-bases", json={"name": "Minimal KB"})
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Minimal KB"
        assert data["slug"] == "minimal-kb"
        assert "id" in data

    async def test_create_with_description(self, client):
        res = await client.post("/v1/knowledge-bases", json={
            "name": "Descriptive KB",
            "description": "A test knowledge base",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["description"] == "A test knowledge base"

    async def test_create_duplicate_name_fails(self, client):
        """Creating a KB with duplicate name should fail."""
        import uuid
        name = f"dup-{uuid.uuid4().hex[:8]}"
        res1 = await client.post("/v1/knowledge-bases", json={"name": name})
        assert res1.status_code == 201
        res2 = await client.post("/v1/knowledge-bases", json={"name": name})
        assert res2.status_code >= 400


class TestGetKnowledgeBase:

    async def test_get_by_slug(self, client):
        """KB is now looked up by slug, not UUID."""
        res = await client.get("/v1/knowledge-bases/test-kb")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Test KB"
        assert data["slug"] == "test-kb"

    async def test_get_not_found(self, client):
        res = await client.get("/v1/knowledge-bases/nonexistent-kb")
        assert res.status_code == 404


class TestUpdateKnowledgeBase:

    async def test_update_name(self, client):
        import uuid
        name = f"update-{uuid.uuid4().hex[:8]}"
        slug = name.lower().replace(" ", "-")
        res = await client.post("/v1/knowledge-bases", json={"name": name})
        assert res.status_code == 201

        new_name = f"Renamed-{uuid.uuid4().hex[:8]}"
        res = await client.patch(f"/v1/knowledge-bases/{slug}", json={"name": new_name})
        assert res.status_code == 200
        assert res.json()["name"] == new_name

    async def test_update_not_found(self, client):
        res = await client.patch("/v1/knowledge-bases/nonexistent", json={"name": "Nope"})
        assert res.status_code == 404


class TestDeleteKnowledgeBase:

    async def test_delete_returns_204(self, client):
        import uuid
        name = f"del-{uuid.uuid4().hex[:8]}"
        slug = name.lower().replace(" ", "-")
        res = await client.post("/v1/knowledge-bases", json={"name": name})
        assert res.status_code == 201

        res = await client.delete(f"/v1/knowledge-bases/{slug}")
        assert res.status_code == 204

        # Verify gone
        res = await client.get(f"/v1/knowledge-bases/{slug}")
        assert res.status_code == 404

    async def test_delete_not_found(self, client):
        res = await client.delete("/v1/knowledge-bases/nonexistent")
        assert res.status_code == 404
