"""
Earnings Calendar Service — Tracks upcoming earnings and dividend dates.

Uses Finnhub free API (60 calls/min). Requires FINNHUB_API_KEY in .env.
If key is not set, returns empty results gracefully — never crashes the system.

Runs once daily at 8:00 AM ET before market open.
Symbols fetched: scanner_universe.yaml always_include list + top 30 from last Scanner run.
"""
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select, delete, desc

from config.settings import settings
from core.database import AsyncSessionLocal
from models.earnings_event import EarningsEvent

FINNHUB_BASE = "https://finnhub.io/api/v1"


class EarningsCalendarService:
    """Fetches and caches upcoming earnings/dividend events from Finnhub."""

    def __init__(self):
        self._api_key = settings.finnhub_api_key

    # ── Public API ──────────────────────────────────────────────────

    async def refresh(self, symbols: list[str]) -> int:
        """
        Fetch earnings dates for the given symbols and store in DB.
        Returns number of events stored.
        """
        if not self._api_key:
            logger.warning("[Earnings] FINNHUB_API_KEY not set — skipping earnings refresh")
            return 0

        if not symbols:
            return 0

        logger.info(f"[Earnings] Refreshing earnings for {len(symbols)} symbols...")

        # Delete stale events (older than today)
        today = date.today()
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(EarningsEvent).where(EarningsEvent.event_date < today)
            )
            await session.commit()

        # Fetch date range: today + 30 days
        from_date = today.isoformat()
        to_date = (today + timedelta(days=30)).isoformat()

        events: list[EarningsEvent] = []

        # Batch symbols to respect Finnhub rate limits (60/min)
        for symbol in symbols:
            try:
                result = await self._fetch_earnings(symbol, from_date, to_date)
                events.extend(result)
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.debug(f"[Earnings] Failed for {symbol}: {e}")

        if events:
            async with AsyncSessionLocal() as session:
                # Remove existing events for these symbols before inserting fresh ones
                syms = list({e.symbol for e in events})
                await session.execute(
                    delete(EarningsEvent).where(EarningsEvent.symbol.in_(syms))
                )
                for event in events:
                    session.add(event)
                await session.commit()

        logger.info(f"[Earnings] Stored {len(events)} earnings events")
        return len(events)

    async def get_upcoming(self, days_ahead: int = 14) -> list[dict]:
        """Return all symbols with events in the next N days."""
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EarningsEvent)
                .where(
                    EarningsEvent.event_date >= today,
                    EarningsEvent.event_date <= cutoff,
                )
                .order_by(EarningsEvent.event_date)
            )
            rows = list(result.scalars().all())
        return [self._to_dict(r) for r in rows]

    async def check_symbol(self, symbol: str) -> dict:
        """Return the next event for a symbol with days_until and risk_level."""
        today = date.today()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EarningsEvent)
                .where(
                    EarningsEvent.symbol == symbol,
                    EarningsEvent.event_date >= today,
                )
                .order_by(EarningsEvent.event_date)
                .limit(1)
            )
            row = result.scalar_one_or_none()
        if not row:
            return {"symbol": symbol, "event": None, "risk_level": "unknown", "days_until": None}
        return self._to_dict(row)

    async def get_high_risk_symbols(self) -> list[str]:
        """Return symbols with earnings in next 7 days."""
        today = date.today()
        cutoff = today + timedelta(days=7)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EarningsEvent.symbol)
                .where(
                    EarningsEvent.event_date >= today,
                    EarningsEvent.event_date <= cutoff,
                    EarningsEvent.event_type == "earnings",
                )
                .distinct()
            )
            rows = result.all()
        return [r[0] for r in rows]

    # ── Internal helpers ─────────────────────────────────────────────

    async def _fetch_earnings(
        self, symbol: str, from_date: str, to_date: str
    ) -> list[EarningsEvent]:
        """Fetch earnings calendar from Finnhub for one symbol."""
        url = f"{FINNHUB_BASE}/calendar/earnings"
        params = {
            "from": from_date,
            "to": to_date,
            "symbol": symbol,
            "token": self._api_key,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()

        events = []
        today = date.today()
        for item in data.get("earningsCalendar", []):
            try:
                event_date = date.fromisoformat(item["date"])
                days_until = (event_date - today).days
                risk_level = self._risk_level(days_until)
                events.append(EarningsEvent(
                    symbol=item.get("symbol", symbol),
                    event_type="earnings",
                    event_date=event_date,
                    days_until=days_until,
                    risk_level=risk_level,
                ))
            except Exception:
                continue

        return events

    @staticmethod
    def _risk_level(days_until: int) -> str:
        if days_until <= 7:
            return "high_risk"
        elif days_until <= 14:
            return "approaching"
        return "safe"

    @staticmethod
    def _to_dict(row: EarningsEvent) -> dict:
        today = date.today()
        days_until = (row.event_date - today).days if row.event_date else None
        return {
            "id": row.id,
            "symbol": row.symbol,
            "event_type": row.event_type,
            "event_date": row.event_date.isoformat() if row.event_date else None,
            "days_until": days_until,
            "risk_level": row.risk_level,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        }
