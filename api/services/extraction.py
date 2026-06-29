"""Knowledge extraction service — uses Ollama LLM to analyze documents
and generate wiki page drafts with suggested tags.
"""

import asyncio
import json
import logging
import re
from collections import Counter

import httpx

from config import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """你是一个知识管理助手。请分析以下文档内容，提取关键知识点，生成一篇结构清晰的 wiki 页面。

要求：
1. 使用 Markdown 格式，包含标题、段落、列表
2. 提炼核心概念、重要结论、可操作的建议
3. 如果有代码示例，保留并添加说明
4. 篇幅适中，不要超过 2000 字
5. 生成 3-8 个标签，中英文均可

你必须严格按照以下 JSON 格式输出，不要包含任何其他文字：

```json
{
  "content": "这里放 wiki 页面的完整 Markdown 内容",
  "tags": ["标签1", "标签2", "标签3"]
}
```

文档标题：{title}

文档内容：
{chunks}
"""

TAG_JSON_RE = re.compile(r'\{[\s\S]*"content"[\s\S]*"tags"[\s\S]*\}', re.MULTILINE)


class ExtractionService:
    def __init__(self, ollama_url: str | None = None, model: str | None = None):
        self.ollama_url = (ollama_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL

    async def extract_from_document(
        self,
        pool,
        document_id: str,
        task_id: str | None = None,
    ) -> dict | None:
        """Analyze a document and return proposed wiki content + tags.

        Returns dict with keys 'content' and 'tags', or None on failure.
        If task_id is provided, updates the extraction_task row on success.
        """
        try:
            result = await self._do_extract(pool, document_id)
            if result and task_id:
                tag_array = "{" + ",".join(f'"{t}"' for t in result["tags"]) + "}"
                await pool.execute(
                    "UPDATE extraction_tasks SET proposed_content = $1, proposed_tags = $2 "
                    "WHERE id = $3",
                    result["content"], result["tags"], task_id,
                )
            return result
        except Exception as e:
            logger.exception("Extraction failed for doc %s", document_id[:8])
            return None

    async def _do_extract(self, pool, document_id: str) -> dict | None:
        # Get document info
        doc = await pool.fetchrow(
            "SELECT title, filename FROM documents WHERE id = $1", document_id
        )
        if not doc:
            logger.error("Document %s not found", document_id)
            return None

        title = doc["title"] or doc["filename"]

        # Get chunks (limit total size to fit LLM context)
        rows = await pool.fetch(
            "SELECT content FROM document_chunks "
            "WHERE document_id = $1 ORDER BY chunk_index "
            "LIMIT 80",
            document_id,
        )
        if not rows:
            logger.warning("No chunks found for doc %s", document_id[:8])
            return None

        # Build context, respect approximate token budget (~6k tokens for input)
        chunks_text = ""
        total_chars = 0
        max_chars = 24000  # ~6k tokens
        for row in rows:
            chunk = row["content"]
            if total_chars + len(chunk) > max_chars:
                # Include partial chunk to fill budget
                remaining = max_chars - total_chars
                if remaining > 200:
                    chunks_text += chunk[:remaining] + "\n...\n"
                break
            chunks_text += chunk + "\n\n"
            total_chars += len(chunk)

        prompt = EXTRACTION_PROMPT.format(title=title, chunks=chunks_text)

        # Call Ollama chat API
        url = f"{self.ollama_url}/api/chat"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), verify=False) as client:
            resp = await client.post(
                url,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw_output = data.get("message", {}).get("content", "")

        if not raw_output:
            logger.error("Empty response from LLM for doc %s", document_id[:8])
            return None

        # Parse JSON from response
        result = self._parse_output(raw_output)
        if not result:
            logger.warning("Failed to parse LLM output for doc %s: %s",
                           document_id[:8], raw_output[:200])
        return result

    def _parse_output(self, raw: str) -> dict | None:
        """Extract JSON from LLM output. Handles markdown code fences and bare markdown."""
        # Try direct JSON parse first
        try:
            data = json.loads(raw)
            if "content" in data:
                return {"content": data["content"], "tags": data.get("tags", [])}
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code fence
        m = TAG_JSON_RE.search(raw)
        if m:
            try:
                data = json.loads(m.group(0))
                if "content" in data:
                    return {"content": data["content"], "tags": data.get("tags", [])}
            except json.JSONDecodeError:
                pass

        # Try to extract structured content + tags from non-JSON output
        content, tags = self._extract_from_markdown(raw)
        return {"content": content, "tags": tags[:8]}

    def _extract_from_markdown(self, raw: str) -> tuple[str, list[str]]:
        """When the LLM outputs markdown instead of JSON, extract content and
        auto-generate tags from headings and key terms."""
        content = raw.strip()

        # Try to pull tags from a trailing JSON block if present
        tags: list[str] = []
        tag_match = re.search(r'"tags"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
        if tag_match:
            tag_str = tag_match.group(1)
            tags = [t.strip().strip('"').strip("'") for t in tag_str.split(",") if t.strip()]

        # Try to pull content from JSON content field
        content_match = re.search(r'"content"\s*:\s*"(.*)"\s*[,}]', raw, re.DOTALL)
        if content_match:
            # This is fragile; prefer the whole raw as content
            pass

        # Auto-generate tags from markdown headings if none found
        if not tags:
            tags = self._infer_tags(content)

        return content, tags

    @staticmethod
    def _infer_tags(content: str) -> list[str]:
        """Generate tags from markdown headings and key terms."""
        # Extract headings (## and ### level)
        headings = re.findall(r'^#{2,4}\s+(.+)$', content, re.MULTILINE)
        tags = []
        seen = set()

        for h in headings:
            h = h.strip()
            # Skip generic headings
            if h.lower() in ('摘要', 'abstract', 'introduction', '引言', '引言\n',
                             '方法', 'method', 'methods', '结论', 'conclusion',
                             '参考', 'references', '总结', 'summary', '概述',
                             '背景', 'background', 'related work', '相关工作',
                             '实验结果', '实验', 'experiments', 'results',
                             '讨论', 'discussion', '未来工作', 'future work'):
                continue
            # Use heading as tag (take first part before colon or pipe)
            tag = h.split('：')[0].split(':')[0].split('|')[0].strip()
            if len(tag) >= 2 and len(tag) <= 30 and tag not in seen:
                tags.append(tag)
                seen.add(tag)
                if len(tags) >= 8:
                    break

        # If still too few, extract English keywords from content
        if len(tags) < 3:
            eng_terms = re.findall(r'\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,2})\b', content)
            # Filter common words
            stopwords = {'The', 'This', 'These', 'They', 'Their', 'Based', 'Using',
                         'From', 'With', 'Each', 'More', 'Such', 'Some', 'Other',
                         'First', 'After', 'Then', 'Also', 'Note', 'One', 'Two'}
            eng_terms = [t for t in eng_terms if t not in stopwords and t not in seen]
            term_counts = Counter(eng_terms)
            for term, _ in term_counts.most_common(8 - len(tags)):
                tags.append(term)
                seen.add(term)

        return tags[:8]


async def run_extraction(pool, document_id: str) -> str | None:
    """Convenience function: create extraction task + run extraction.
    Returns task_id on success.
    """
    # Create task
    row = await pool.fetchrow(
        "INSERT INTO extraction_tasks (document_id) VALUES ($1) "
        "RETURNING id",
        document_id,
    )
    task_id = str(row["id"])

    # Run extraction
    service = ExtractionService()
    result = await service.extract_from_document(pool, document_id, task_id)

    if result:
        logger.info("Extraction completed for doc %s → task %s", document_id[:8], task_id[:8])
        return task_id
    else:
        logger.warning("Extraction returned empty for doc %s", document_id[:8])
        return task_id  # task exists, just shows empty content for manual review
