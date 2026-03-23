"""
News Feed Service — Fetches and stores market and company headlines from Finnhub.

Stores raw headlines — does NOT analyze or score them. That is the LLM's job in Phase B.
Runs twice daily at 9:00 AM and 12:00 PM ET. Auto-prunes headlines older than 48 hours.

Requires FINNHUB_API_KEY in .env. If not set, skips silently.
"""
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select, delete, desc

from config.settings import settings
from core.database import AsyncSessionLocal
from models.news_headline import NewsHeadline

FINNHUB_BASE = "https://finnhub.io/api/v1"


class NewsFeedService:
    """Fetches market and company news from Finnhub and stores unique headlines."""

    def __init__(self):
        self._api_key = settings.finnhub_api_key

    # ── Public API ──────────────────────────────────────────────────

    async def refresh(self, symbols: Optional[list[str]] = None) -> int:
        """
        Fetch latest headlines and store new ones (dedup by headline text).
        Returns number of new headlines stored.
        """
        if not self._api_key:
            logger.debug("[News] FINNHUB_API_KEY not set — skipping news refresh")
            return 0

        # Prune headlines older than 48 hours
        cutoff = datetime.utcnow() - timedelta(hours=48)
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(NewsHeadline).where(NewsHeadline.published_at < cutoff)
            )
            await session.commit()

        new_count = 0

        # General market news
        try:
            market_headlines = await self._fetch_market_news()
            new_count += await self._store_headlines(market_headlines, "general")
        except Exception as e:
            logger.debug(f"[News] Market news fetch failed: {e}")

        # Company-specific news for provided symbols (limit to avoid rate limits)
        if symbols:
            for symbol in symbols[:20]:  # cap at 20 symbols per refresh
                try:
                    company_headlines = await self._fetch_company_news(symbol)
                    new_count += await self._store_headlines(company_headlines, "company", symbol)
                except Exception as e:
                    logger.debug(f"[News] Company news for {symbol} failed: {e}")

        if new_count > 0:
            logger.info(f"[News] Stored {new_count} new headlines")
        return new_count

    async def get_recent(self, n: int = 20) -> list[dict]:
        """Return N most recent headlines."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsHeadline)
                .order_by(desc(NewsHeadline.published_at))
                .limit(n)
            )
            rows = list(result.scalars().all())
        return [self._to_dict(r) for r in rows]

    async def get_for_symbol(self, symbol: str, n: int = 10) -> list[dict]:
        """Return headlines mentioning a symbol."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsHeadline)
                .where(NewsHeadline.symbols.contains(symbol))
                .order_by(desc(NewsHeadline.published_at))
                .limit(n)
            )
            rows = list(result.scalars().all())
        return [self._to_dict(r) for r in rows]

    async def get_market_summary(self, n: int = 10) -> list[dict]:
        """Return top general market headlines."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsHeadline)
                .where(NewsHeadline.category == "general")
                .order_by(desc(NewsHeadline.published_at))
                .limit(n)
            )
            rows = list(result.scalars().all())
        return [self._to_dict(r) for r in rows]

    # ── Internal helpers ─────────────────────────────────────────────

    async def _fetch_market_news(self) -> list[dict]:
        url = f"{FINNHUB_BASE}/news"
        params = {"category": "general", "token": self._api_key}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            return resp.json() or []

    async def _fetch_company_news(self, symbol: str) -> list[dict]:
        today = datetime.utcnow().date()
        from_date = (today - timedelta(days=2)).isoformat()
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
            return data[:5]  # cap at 5 per symbol

    async def _store_headlines(
        self, items: list[dict], category: str, symbol: str = ""
    ) -> int:
        """Store new headlines, dedup by headline text. Returns count stored."""
        if not items:
            return 0

        # Load existing headlines to dedup
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsHeadline.headline)
                .where(NewsHeadline.category == category)
                .order_by(desc(NewsHeadline.published_at))
                .limit(200)
            )
            existing = {r[0] for r in result.all()}

        new_rows = []
        for item in items:
            headline_text = item.get("headline", "")
            if not headline_text or headline_text in existing:
                continue

            # Parse published_at from Unix timestamp or string
            raw_ts = item.get("datetime") or item.get("publishedAt")
            try:
                if isinstance(raw_ts, (int, float)):
                    published_at = datetime.utcfromtimestamp(raw_ts)
                elif isinstance(raw_ts, str):
                    published_at = datetime.fromisoformat(raw_ts)
                else:
                    published_at = datetime.utcnow()
            except Exception:
                published_at = datetime.utcnow()

            # Only keep headlines from last 48 hours
            if (datetime.utcnow() - published_at).total_seconds() > 48 * 3600:
                continue

            related_symbols = item.get("related", "") or symbol
            new_rows.append(NewsHeadline(
                headline=headline_text,
                source=item.get("source", ""),
                url=item.get("url"),
                symbols=related_symbols,
                category=category,
                published_at=published_at,
            ))
            existing.add(headline_text)

        if new_rows:
            async with AsyncSessionLocal() as session:
                for row in new_rows:
                    session.add(row)
                await session.commit()

        return len(new_rows)

    @staticmethod
    def _to_dict(row: NewsHeadline) -> dict:
        return {
            "id": row.id,
            "headline": row.headline,
            "source": row.source,
            "url": row.url,
            "symbols": row.symbols,
            "category": row.category,
            "published_at": row.published_at.isoformat() if row.published_at else None,
        }
