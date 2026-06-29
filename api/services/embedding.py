import asyncio
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, ollama_url: str | None = None, model: str | None = None, dim: int | None = None):
        self.ollama_url = (ollama_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.EMBEDDING_MODEL
        self.dim = dim or settings.EMBEDDING_DIM

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        results = await self.embed_batch([text])
        return results[0] if results else []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts via Ollama API."""
        if not texts:
            return []

        # Filter empty strings
        valid_texts = [t.strip() for t in texts if t and t.strip()]
        if not valid_texts:
            return [[0.0] * self.dim for _ in texts]

        url = f"{self.ollama_url}/api/embed"
        results = []
        for text in valid_texts:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                    resp = await client.post(
                        url,
                        json={"model": self.model, "input": text},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    embedding = data.get("embeddings", [[]])[0]
                    # Pad or truncate to configured dim
                    if len(embedding) < self.dim:
                        embedding = embedding + [0.0] * (self.dim - len(embedding))
                    elif len(embedding) > self.dim:
                        embedding = embedding[:self.dim]
                    results.append(embedding)
            except Exception as e:
                logger.warning("Embedding failed for text (len=%d): %s", len(text), e)
                results.append([0.0] * self.dim)

        return results


async def embed_chunks(
    chunks: list[dict],
    api_url: str | None = None,
    model: str | None = None,
) -> list[list[float]]:
    """Standalone helper: embed a list of chunks (each has 'content' key)."""
    service = EmbeddingService(ollama_url=api_url, model=model)
    texts = [c.get("content", "") for c in chunks]
    return await service.embed_batch(texts)
