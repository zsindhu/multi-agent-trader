"""
Earnings Calendar Service — Universe-scale earnings ingestion.

Uses Finnhub's bulk /calendar/earnings endpoint to fetch ALL upcoming
earnings in a single API call (vs the old per-symbol approach that only
covered ~30 names). Filters to the optionable universe at ingestion.

Runs daily at 6:00 AM ET before any Tier 2a cycles. Refreshes the next
30 days so the 14-day window queried by Tier 2a always has fresh data.

Requires FINNHUB_API_KEY in .env. If not set, returns empty gracefully.
"""
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select, delete

from config.settings import settings
from core.database import AsyncSessionLocal
from models.earnings_event import EarningsEvent
from models.name_observation import NameObservation

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Coverage sanity check: if total events for next 30 days drops below
# this threshold after a refresh, log a WARNING so the issue surfaces
# immediately rather than being discovered weeks later.
MIN_COVERAGE_THRESHOLD = 200


class EarningsCalendarService:
    """Fetches and caches upcoming earnings events from Finnhub."""

    def __init__(self):
        self._api_key = settings.finnhub_api_key

    # ── Public API ──────────────────────────────────────────────────

    async def refresh(self, symbols: list[str] = None) -> int:
        """
        Fetch the full upcoming earnings calendar from Finnhub's bulk endpoint
        and store in DB. Filters to the optionable universe.

        The symbols parameter is accepted for backward compatibility but ignored —
        the bulk endpoint returns all earnings regardless.

        Returns number of events stored.
        """
        if not self._api_key:
            logger.warning("[Earnings] FINNHUB_API_KEY not set — skipping earnings refresh")
            return 0

        today = date.today()
        from_date = today.isoformat()
        to_date = (today + timedelta(days=30)).isoformat()

        logger.info(f"[Earnings] Bulk refresh: {from_date} to {to_date}")

        # Step 1: Fetch in 7-day chunks to avoid Finnhub free-tier ~1500-event cap.
        # A single 30-day request silently drops events beyond ~1500, concentrating
        # results in the latest 7 days. Chunking ensures full coverage.
        raw_events = []
        chunk_days = 7
        chunk_start = today
        while chunk_start < today + timedelta(days=30):
            chunk_end = min(chunk_start + timedelta(days=chunk_days), today + timedelta(days=30))
            try:
                chunk = await self._fetch_bulk_earnings(chunk_start.isoformat(), chunk_end.isoformat())
                raw_events.extend(chunk)
                logger.info(f"[Earnings] Chunk {chunk_start} to {chunk_end}: {len(chunk)} events")
            except Exception as e:
                logger.warning(f"[Earnings] Chunk {chunk_start} to {chunk_end} failed: {e}")
            chunk_start = chunk_end
            await asyncio.sleep(1.0)

        # Deduplicate by (symbol, date) — chunks may overlap at boundaries
        seen = set()
        deduped = []
        for evt in raw_events:
            key = (evt.get("symbol"), evt.get("date"))
            if key not in seen:
                seen.add(key)
                deduped.append(evt)
        raw_events = deduped

        if not raw_events:
            logger.warning("[Earnings] All chunks returned zero events")
            return 0

        logger.info(f"[Earnings] Total raw events after chunking + dedup: {len(raw_events)}")

        # Step 2: Get the optionable universe for filtering
        universe = await self._get_optionable_universe()
        if universe:
            filtered = [e for e in raw_events if e.get("symbol") in universe]
            logger.info(f"[Earnings] Filtered to {len(filtered)} events in optionable universe (from {len(raw_events)} raw)")
        else:
            # No universe data available — keep all events rather than dropping everything
            filtered = raw_events
            logger.warning("[Earnings] No universe data available — keeping all events unfiltered")

        # Step 3: Build EarningsEvent rows
        events = []
        for item in filtered:
            try:
                event_date = date.fromisoformat(item["date"])
                days_until = (event_date - today).days
                events.append(EarningsEvent(
                    symbol=item["symbol"],
                    event_type="earnings",
                    event_date=event_date,
                    days_until=days_until,
                    risk_level=self._risk_level(days_until),
                ))
            except Exception:
                continue

        # Step 4: Replace all events (delete old, insert fresh)
        async with AsyncSessionLocal() as session:
            await session.execute(delete(EarningsEvent))
            for event in events:
                session.add(event)
            await session.commit()

        logger.info(f"[Earnings] Stored {len(events)} earnings events ({len(set(e.symbol for e in events))} distinct symbols)")

        # Step 5: Coverage sanity check
        if len(events) < MIN_COVERAGE_THRESHOLD:
            logger.warning(
                f"[Earnings] COVERAGE WARNING: only {len(events)} events for next 30 days "
                f"(threshold: {MIN_COVERAGE_THRESHOLD}). Possible API issue or off-season."
            )

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

    async def _fetch_bulk_earnings(self, from_date: str, to_date: str) -> list[dict]:
        """Fetch the full earnings calendar from Finnhub (no symbol filter)."""
        url = f"{FINNHUB_BASE}/calendar/earnings"
        params = {
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.error(f"[Earnings] Bulk endpoint HTTP {resp.status_code}: {resp.text[:200]}")
                return []
            data = resp.json()

        return data.get("earningsCalendar", [])

    async def _get_optionable_universe(self) -> set[str]:
        """Get the set of optionable symbols from today's Tier 1 observations.
        Falls back to yesterday's if today's aren't available yet."""
        try:
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)

            async with AsyncSessionLocal() as session:
                # Try today first
                result = await session.execute(
                    select(NameObservation.symbol)
                    .where(NameObservation.tier == 1)
                    .where(NameObservation.was_considered == True)
                    .where(NameObservation.timestamp >= today_start)
                )
                symbols = {r[0] for r in result.all()}

                if not symbols:
                    # Fall back to yesterday
                    result = await session.execute(
                        select(NameObservation.symbol)
                        .where(NameObservation.tier == 1)
                        .where(NameObservation.was_considered == True)
                        .where(NameObservation.timestamp >= yesterday_start)
                    )
                    symbols = {r[0] for r in result.all()}

            if symbols:
                logger.info(f"[Earnings] Universe filter: {len(symbols)} optionable symbols")
            return symbols

        except Exception as e:
            logger.warning(f"[Earnings] Universe lookup failed: {e}")
            return set()

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
