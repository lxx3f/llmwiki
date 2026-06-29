import logging
from uuid import UUID

import asyncpg

from config import settings
from services.embedding import EmbeddingService

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.embedding = EmbeddingService()
        self.available = False  # Set to True after first successful embedding call

    async def search_similar(
        self,
        query: str,
        kb_id: UUID | str,
        top_k: int = 10,
    ) -> list[dict]:
        """Vector similarity search over document chunks."""
        query_embedding = await self.embedding.embed_text(query)
        if not query_embedding or all(v == 0.0 for v in query_embedding):
            # Fallback: return empty, caller should use text search instead
            logger.warning("No embedding generated for query, falling back to text search")
            return []

        self.available = True
        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"

        rows = await self.pool.fetch(
            "SELECT dc.content, dc.page, dc.chunk_index, dc.header_breadcrumb, "
            "  d.filename, d.title, d.path, d.file_type, "
            "  1 - (dc.embedding <=> $2::vector) AS similarity "
            "FROM document_chunks dc "
            "JOIN documents d ON dc.document_id = d.id "
            "WHERE dc.knowledge_base_id = $1 "
            "  AND NOT d.archived "
            "  AND dc.embedding IS NOT NULL "
            "ORDER BY dc.embedding <=> $2::vector "
            "LIMIT $3",
            str(kb_id), embedding_str, top_k,
        )
        return [dict(r) for r in rows]

    async def search_hybrid(
        self,
        query: str,
        kb_id: UUID | str,
        top_k: int = 10,
    ) -> list[dict]:
        """Combine vector search with PGroonga full-text search."""
        vector_results = await self.search_similar(query, kb_id, top_k)

        # Also try PGroonga full-text search
        try:
            text_results = await self.pool.fetch(
                "SELECT dc.content, dc.page, dc.chunk_index, dc.header_breadcrumb, "
                "  d.filename, d.title, d.path, d.file_type, "
                "  pgroonga_score(dc.tableoid, dc.ctid) AS similarity "
                "FROM document_chunks dc "
                "JOIN documents d ON dc.document_id = d.id "
                "WHERE dc.knowledge_base_id = $1 "
                "  AND dc.content &@~ $2 "
                "  AND NOT d.archived "
                "ORDER BY pgroonga_score(dc.tableoid, dc.ctid) DESC "
                "LIMIT $3",
                str(kb_id), query, top_k,
            )
            text_dicts = [dict(r) for r in text_results]
        except Exception:
            text_dicts = []

        # Merge results, deduplicate by chunk content, sort by similarity
        seen = set()
        merged = []
        for r in vector_results + text_dicts:
            key = r["content"][:100]
            if key not in seen:
                seen.add(key)
                merged.append(r)

        merged.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        return merged[:top_k]
