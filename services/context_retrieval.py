"""
Context Retrieval Service — Semantic search across playbook, outcomes,
and cycle snapshots via pgvector embeddings.

Wraps EmbeddingsService.search() with entity-aware methods that return
structured results. Used by get_playbook() for semantic queries and
by the future RAG Chat Agent (Phase 2).
"""
from typing import Optional

from loguru import logger
from sqlalchemy import select

from core.database import AsyncSessionLocal
from services.embeddings import EmbeddingsService
from models.playbook_entry import PlaybookEntry
from models.trade_outcome import TradeOutcome
from models.trade import Trade
from models.cycle_snapshot import CycleSnapshot


class ContextRetrievalService:
    """Semantic + SQL retrieval across the research data layer."""

    def __init__(self):
        self._embeddings = EmbeddingsService()

    @property
    def is_enabled(self) -> bool:
        return self._embeddings.is_enabled

    async def search_playbook(self, query: str, limit: int = 10) -> list[dict]:
        """
        Semantic search over playbook entries.
        Returns matched entries with similarity scores and full content.
        """
        if not self.is_enabled:
            return []

        # Overfetch: deactivated entries keep their embeddings and are only
        # filtered after the vector query, which would silently shrink the
        # result set below `limit`.
        hits = await self._embeddings.search(
            query_text=query,
            source_table="playbook_entries",
            limit=limit * 3,
        )

        if not hits:
            return []

        # Hydrate with full playbook entry data
        source_ids = [h["source_id"] for h in hits]
        similarity_map = {h["source_id"]: h["similarity"] for h in hits}

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PlaybookEntry)
                    .where(PlaybookEntry.id.in_(source_ids))
                    .where(PlaybookEntry.active == True)
                )
                entries = result.scalars().all()

            return sorted(
                [
                    {
                        "id": e.id,
                        "category": e.category,
                        "content": e.content,
                        "confidence": e.confidence,
                        "validated": e.validated,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                        "similarity": round(similarity_map.get(e.id, 0), 4),
                    }
                    for e in entries
                ],
                key=lambda x: x["similarity"],
                reverse=True,
            )[:limit]
        except Exception as e:
            logger.debug(f"[Retrieval] Playbook hydration failed: {e}")
            return []

    async def search_outcomes(self, query: str, limit: int = 10) -> list[dict]:
        """
        Semantic search over trade outcomes.
        Returns matched outcomes with trade symbol and similarity scores.
        """
        if not self.is_enabled:
            return []

        hits = await self._embeddings.search(
            query_text=query,
            source_table="trade_outcomes",
            limit=limit,
        )

        if not hits:
            return []

        source_ids = [h["source_id"] for h in hits]
        similarity_map = {h["source_id"]: h["similarity"] for h in hits}

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TradeOutcome, Trade.symbol)
                    .join(Trade, TradeOutcome.trade_id == Trade.id)
                    .where(TradeOutcome.id.in_(source_ids))
                )
                rows = result.all()

            return sorted(
                [
                    {
                        "id": o.id,
                        "symbol": symbol,
                        "outcome": o.outcome,
                        "pnl_dollars": o.pnl_dollars,
                        "pnl_percent": o.pnl_percent,
                        "holding_days": o.holding_days,
                        "funnel_driven": o.funnel_driven,
                        "similarity": round(similarity_map.get(o.id, 0), 4),
                    }
                    for o, symbol in rows
                ],
                key=lambda x: x["similarity"],
                reverse=True,
            )
        except Exception as e:
            logger.debug(f"[Retrieval] Outcome hydration failed: {e}")
            return []

    async def search_cycles(self, query: str, limit: int = 10) -> list[dict]:
        """
        Semantic search over cycle snapshot reasoning.
        Returns matched cycles with regime context and similarity scores.
        """
        if not self.is_enabled:
            return []

        hits = await self._embeddings.search(
            query_text=query,
            source_table="cycle_snapshots",
            limit=limit,
        )

        if not hits:
            return []

        source_ids = [h["source_id"] for h in hits]
        similarity_map = {h["source_id"]: h["similarity"] for h in hits}

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(CycleSnapshot)
                    .where(CycleSnapshot.id.in_(source_ids))
                )
                snapshots = result.scalars().all()

            return sorted(
                [
                    {
                        "id": s.id,
                        "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                        "regime": s.regime,
                        "vix_level": s.vix_level,
                        "actions_decided": s.actions_decided,
                        "actions_executed": s.actions_executed,
                        "summary": (s.summary or "")[:200],
                        "similarity": round(similarity_map.get(s.id, 0), 4),
                    }
                    for s in snapshots
                ],
                key=lambda x: x["similarity"],
                reverse=True,
            )
        except Exception as e:
            logger.debug(f"[Retrieval] Cycle hydration failed: {e}")
            return []

    async def search_all(self, query: str, limit: int = 5) -> dict:
        """
        Search across all entity types. Returns top results from each.
        Useful for the RAG Chat Agent to get broad context.
        """
        playbook = await self.search_playbook(query, limit=limit)
        outcomes = await self.search_outcomes(query, limit=limit)
        cycles = await self.search_cycles(query, limit=limit)

        return {
            "playbook": playbook,
            "outcomes": outcomes,
            "cycles": cycles,
        }

    async def get_context_for_symbol(self, symbol: str, limit: int = 10) -> dict:
        """
        Get all context for a specific symbol — playbook notes,
        trade outcomes, and relevant cycle reasoning.
        """
        # SQL-based: direct queries for symbol-specific data
        results = {"playbook": [], "outcomes": [], "cycles": []}

        try:
            async with AsyncSessionLocal() as session:
                # Symbol notes from playbook
                pb_result = await session.execute(
                    select(PlaybookEntry)
                    .where(PlaybookEntry.active == True)
                    .where(PlaybookEntry.category == "symbol_note")
                    .where(PlaybookEntry.content.ilike(f"%{symbol}%"))
                    .order_by(PlaybookEntry.created_at.desc())
                    .limit(limit)
                )
                results["playbook"] = [
                    {
                        "id": e.id,
                        "category": e.category,
                        "content": e.content,
                        "confidence": e.confidence,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in pb_result.scalars().all()
                ]

                # Trade outcomes for symbol
                out_result = await session.execute(
                    select(TradeOutcome)
                    .join(Trade, TradeOutcome.trade_id == Trade.id)
                    .where(Trade.symbol == symbol)
                    .order_by(TradeOutcome.labeled_at.desc())
                    .limit(limit)
                )
                results["outcomes"] = [
                    {
                        "id": o.id,
                        "outcome": o.outcome,
                        "pnl_dollars": o.pnl_dollars,
                        "holding_days": o.holding_days,
                        "funnel_driven": o.funnel_driven,
                    }
                    for o in out_result.scalars().all()
                ]
        except Exception as e:
            logger.debug(f"[Retrieval] Symbol context failed for {symbol}: {e}")

        # Semantic search for cycle reasoning mentioning the symbol
        if self.is_enabled:
            results["cycles"] = await self.search_cycles(
                f"trade decision {symbol}", limit=limit
            )

        return results
