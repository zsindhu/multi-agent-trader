"""
Embeddings Service — Computes vector embeddings via OpenAI API and persists
them to the reasoning_embeddings table for semantic search.

Falls back gracefully if OpenAI isn't configured. Embedding failures never
block the calling code — they're best-effort enrichment.
"""
from typing import Optional
from loguru import logger
from openai import AsyncOpenAI

from config.settings import settings
from core.database import AsyncSessionLocal
from models.reasoning_embedding import ReasoningEmbedding


class EmbeddingsService:
    """Computes and stores vector embeddings."""

    MODEL = "text-embedding-3-small"
    DIMENSION = 1536

    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        if settings.openai_api_key:
            self.client = AsyncOpenAI(api_key=settings.openai_api_key)
            logger.info(f"[Embeddings] Initialized with model {self.MODEL}")
        else:
            logger.warning("[Embeddings] No OPENAI_API_KEY — semantic search disabled")

    @property
    def is_enabled(self) -> bool:
        return self.client is not None

    async def embed_and_store(
        self,
        text: str,
        source_table: str,
        source_id: int,
    ) -> Optional[int]:
        """
        Compute an embedding for `text` and store it in reasoning_embeddings.
        Returns the new embedding row ID, or None on failure.

        Best-effort: never raises. Logs errors and returns None.
        """
        if not self.is_enabled:
            return None

        if not text or not text.strip():
            return None

        try:
            # Truncate to ~8000 tokens worth of text (rough char approximation)
            truncated = text[:30000]

            response = await self.client.embeddings.create(
                model=self.MODEL,
                input=truncated,
            )
            vector = response.data[0].embedding

            async with AsyncSessionLocal() as session:
                row = ReasoningEmbedding(
                    source_table=source_table,
                    source_id=source_id,
                    text_excerpt=truncated[:500],
                    embedding=vector,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row.id
        except Exception as e:
            logger.error(f"[Embeddings] embed_and_store failed for {source_table}#{source_id}: {e}")
            return None

    async def search(
        self,
        query_text: str,
        source_table: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Semantic search across stored embeddings.
        Returns a list of dicts with source_table, source_id, text_excerpt,
        and similarity score (0-1, higher = more similar).
        """
        if not self.is_enabled:
            return []

        try:
            response = await self.client.embeddings.create(
                model=self.MODEL,
                input=query_text[:30000],
            )
            query_vector = response.data[0].embedding

            from sqlalchemy import text as sql_text
            async with AsyncSessionLocal() as session:
                base_query = """
                    SELECT id, source_table, source_id, text_excerpt,
                           1 - (embedding <=> :query_vec::vector) AS similarity
                    FROM reasoning_embeddings
                """
                if source_table:
                    base_query += " WHERE source_table = :src_table"
                base_query += " ORDER BY embedding <=> :query_vec::vector LIMIT :lim"

                params = {"query_vec": str(query_vector), "lim": limit}
                if source_table:
                    params["src_table"] = source_table

                result = await session.execute(sql_text(base_query), params)
                rows = result.mappings().all()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[Embeddings] search failed: {e}")
            return []
