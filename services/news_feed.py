"""
News Feed Service — Two-stream news architecture:

1. Macro stream: broad-market news → macro_news_events table (90d retention).
   Topic-tagged at ingestion. Environmental context for future agents.
   Does NOT affect Tier 2a scoring.

2. Symbol stream: per-name company news → symbol_news_headlines table (35d retention).
   Fetched on-demand for Tier 2a's top mechanical scorers. Feeds the
   news_density rule.

Requires FINNHUB_API_KEY in .env. If not set, skips silently.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select, delete, desc, func as sa_func

from config.settings import settings
from core.database import AsyncSessionLocal
from models.macro_news_event import MacroNewsEvent
from models.symbol_news_headline import SymbolNewsHeadline

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Topic keyword map for macro news tagging.
# A headline can match multiple topics; stored as JSON array.
TOPIC_KEYWORDS = {
    "monetary_policy": ["fed ", "fomc", "rate hike", "rate cut", "powell", "central bank", "monetary policy"],
    "inflation_data": ["cpi", "inflation", "pce", "ppi ", "consumer price"],
    "macro_data": ["gdp", "unemployment", "jobs report", "payrolls", "ism ", "retail sales"],
    "geopolitical": ["war ", "conflict", "sanctions", "tariff", "geopolit"],
    "market_action": ["s&p 500", "nasdaq", " dow ", "market rally", "market sell", "vix ", "bull market", "bear market"],
}


def _tag_topics(headline: str) -> list[str]:
    """Tag a headline with matching topics. Returns list of topic strings."""
    lower = headline.lower()
    topics = [topic for topic, keywords in TOPIC_KEYWORDS.items()
              if any(kw in lower for kw in keywords)]
    return topics if topics else ["general"]


class NewsFeedService:
    """Two-stream news: macro (scheduled) + symbol-specific (on-demand)."""

    def __init__(self):
        self._api_key = settings.finnhub_api_key

    # ── Macro news (scheduled, twice daily) ──────────────────────

    async def refresh_macro(self) -> int:
        """Fetch general market news, topic-tag, store in macro_news_events. Returns count stored."""
        if not self._api_key:
            logger.debug("[News] FINNHUB_API_KEY not set — skipping macro refresh")
            return 0

        # Prune headlines older than 90 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(MacroNewsEvent).where(MacroNewsEvent.published_at < cutoff)
            )
            await session.commit()

        try:
            raw = await self._fetch_market_news()
        except Exception as e:
            logger.warning(f"[News] Macro news fetch failed: {e}")
            return 0

        # Dedup against existing headlines
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MacroNewsEvent.headline)
                .order_by(desc(MacroNewsEvent.published_at))
                .limit(500)
            )
            existing = {r[0] for r in result.all()}

        new_rows = []
        for item in raw:
            headline_text = item.get("headline", "")
            if not headline_text or headline_text in existing:
                continue

            published_at = self._parse_timestamp(item.get("datetime"))
            if published_at is None:
                continue

            new_rows.append(MacroNewsEvent(
                headline=headline_text,
                summary=item.get("summary", "")[:500] if item.get("summary") else None,
                source=item.get("source", ""),
                url=item.get("url"),
                published_at=published_at,
                topics=_tag_topics(headline_text),
            ))
            existing.add(headline_text)

        if new_rows:
            async with AsyncSessionLocal() as session:
                for row in new_rows:
                    session.add(row)
                await session.commit()

        if new_rows:
            logger.info(f"[News] Stored {len(new_rows)} macro headlines")
        return len(new_rows)

    # ── Symbol news (on-demand for Tier 2a) ──────────────────────

    async def fetch_symbol_news(self, symbol: str, cache_ttl_hours: float = 4.0) -> int:
        """
        Fetch company news for a symbol if not cached recently.
        Returns count of new headlines stored.
        """
        if not self._api_key:
            return 0

        # Check cache: skip if we have recent data
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cache_ttl_hours)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(sa_func.max(SymbolNewsHeadline.created_at))
                .where(SymbolNewsHeadline.symbol == symbol)
            )
            last_fetch = result.scalar()

        if last_fetch and last_fetch.replace(tzinfo=timezone.utc) >= cutoff:
            return 0  # Cache is fresh

        try:
            raw = await self._fetch_company_news(symbol)
        except Exception as e:
            logger.debug(f"[News] Company news fetch failed for {symbol}: {e}")
            return -1  # Signal fetch failure

        # Dedup
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SymbolNewsHeadline.headline)
                .where(SymbolNewsHeadline.symbol == symbol)
                .order_by(desc(SymbolNewsHeadline.published_at))
                .limit(100)
            )
            existing = {r[0] for r in result.all()}

        new_rows = []
        for item in raw:
            headline_text = item.get("headline", "")
            if not headline_text or headline_text in existing:
                continue

            published_at = self._parse_timestamp(item.get("datetime"))
            if published_at is None:
                continue

            new_rows.append(SymbolNewsHeadline(
                symbol=symbol,
                headline=headline_text,
                summary=item.get("summary", "")[:500] if item.get("summary") else None,
                source=item.get("source", ""),
                url=item.get("url"),
                published_at=published_at,
            ))
            existing.add(headline_text)

        if new_rows:
            async with AsyncSessionLocal() as session:
                for row in new_rows:
                    session.add(row)
                await session.commit()

        return len(new_rows)

    async def prune_symbol_news(self) -> int:
        """Remove symbol news older than 35 days. Called during macro refresh."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=35)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(SymbolNewsHeadline).where(SymbolNewsHeadline.published_at < cutoff)
            )
            await session.commit()
            return result.rowcount or 0

    # ── Read methods (for API routes and agents) ─────────────────

    async def get_recent(self, n: int = 20) -> list[dict]:
        """Return N most recent macro headlines."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MacroNewsEvent)
                .order_by(desc(MacroNewsEvent.published_at))
                .limit(n)
            )
            rows = list(result.scalars().all())
        return [self._macro_to_dict(r) for r in rows]

    async def get_market_summary(self, n: int = 10) -> list[dict]:
        """Return top macro headlines."""
        return await self.get_recent(n)

    async def get_for_symbol(self, symbol: str, n: int = 10) -> list[dict]:
        """Return headlines for a symbol from symbol_news_headlines."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SymbolNewsHeadline)
                .where(SymbolNewsHeadline.symbol == symbol)
                .order_by(desc(SymbolNewsHeadline.published_at))
                .limit(n)
            )
            rows = list(result.scalars().all())
        return [self._symbol_to_dict(r) for r in rows]

    # ── Backward compat: refresh() calls refresh_macro() ─────────

    async def refresh(self, symbols: Optional[list[str]] = None) -> int:
        """Backward-compatible refresh. Calls refresh_macro + prune_symbol_news."""
        count = await self.refresh_macro()
        await self.prune_symbol_news()
        return count

    # ── Internal helpers ─────────────────────────────────────────

    async def _fetch_market_news(self) -> list[dict]:
        url = f"{FINNHUB_BASE}/news"
        params = {"category": "general", "token": self._api_key}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            return resp.json() or []

    async def _fetch_company_news(self, symbol: str) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        from_date = (today - timedelta(days=7)).isoformat()
        to_date = today.isoformat()
        url = f"{FINNHUB_BASE}/company-news"
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json() or []
            return data[:10]  # cap per symbol

    @staticmethod
    def _parse_timestamp(raw_ts) -> Optional[datetime]:
        try:
            if isinstance(raw_ts, (int, float)):
                return datetime.fromtimestamp(raw_ts, tz=timezone.utc)
            elif isinstance(raw_ts, str):
                dt = datetime.fromisoformat(raw_ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except Exception:
            pass
        return None

    @staticmethod
    def _macro_to_dict(row: MacroNewsEvent) -> dict:
        return {
            "id": row.id,
            "headline": row.headline,
            "summary": row.summary,
            "source": row.source,
            "url": row.url,
            "topics": row.topics,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "category": "general",
        }

    @staticmethod
    def _symbol_to_dict(row: SymbolNewsHeadline) -> dict:
        return {
            "id": row.id,
            "headline": row.headline,
            "symbol": row.symbol,
            "source": row.source,
            "url": row.url,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "category": "company",
            "symbols": row.symbol,
        }
