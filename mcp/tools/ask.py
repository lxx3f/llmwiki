"""Ask tool — semantic Q&A over the wiki via vector search."""

from mcp.server.fastmcp import FastMCP, Context

from db import query
from .helpers import get_user_id, resolve_kb

# We import lazily to avoid dependency on the API process
_rag_service = None


async def _get_rag_service(pool):
    global _rag_service
    if _rag_service is None:
        from services.rag import RAGService
        _rag_service = RAGService(pool)
    return _rag_service


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="ask",
        description=(
            "Ask a question and get an answer based on the wiki's content.\n\n"
            "Uses semantic vector search (when available) combined with full-text search "
            "to find the most relevant content across all documents in the knowledge base.\n\n"
            "If the answer reveals a valuable insight, consider creating a new wiki page "
            "or updating an existing one to capture it — explorations should compound."
        ),
    )
    async def ask(
        ctx: Context,
        knowledge_base: str,
        question: str,
        top_k: int = 10,
    ) -> str:
        user_id = get_user_id(ctx)

        kb = await resolve_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        # Try vector search first
        try:
            from db import get_pool
            pool = await get_pool()
            rag = await _get_rag_service(pool)
            results = await rag.search_hybrid(question, kb["id"], top_k)
        except Exception as e:
            # Fallback to PGroonga full-text search
            results = await query(
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
                kb["id"], question, top_k,
            )

        if not results:
            return f"No relevant content found for '{question}' in {kb['name']}."

        # Format results for Claude to synthesize
        lines = [
            f"**Query**: {question}",
            f"**Knowledge Base**: {kb['name']} ({kb['slug']})",
            f"**Relevant context** ({len(results)} chunks):\n",
        ]
        for i, r in enumerate(results, 1):
            source = f"{r.get('path', '')}{r.get('filename', '')}"
            page_info = f" (p.{r['page']})" if r.get('page') else ""
            sim = r.get('similarity', 0)
            sim_str = f" [relevance: {sim:.2f}]" if sim else ""
            lines.append(f"### Chunk {i} — {source}{page_info}{sim_str}")
            if r.get('header_breadcrumb'):
                lines.append(f"Section: {r['header_breadcrumb']}")
            lines.append(f"\n{r['content']}\n")

        lines.append(
            "\n---\n"
            "**Instructions**: Synthesize an answer from the context above. "
            "Cite sources using the format `[^1]: filename, p.X`. "
            "If the context is insufficient, say so. "
            "If this answer contains a valuable insight, suggest creating or updating a wiki page."
        )

        return "\n".join(lines)
