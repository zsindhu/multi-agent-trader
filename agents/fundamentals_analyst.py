"""
Fundamentals Analyst — On-demand qualitative context for the Lead Agent.

When the Lead Agent calls get_fundamentals(symbol), this agent:
1. Checks agent_messages for a cached summary (<24h old)
2. If not cached, gathers context (EDGAR filing text, earnings, macro, news)
3. Sends to Llama 3.3 for a 3-5 sentence fundamentals summary
4. Caches the result in agent_messages

NOT a batch agent. Runs on-demand, ~5-10 calls per Lead Agent cycle.
Cost: ~$0.30/month at current usage.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, desc

from config.settings import settings
from core.database import AsyncSessionLocal
from models.agent_message import AgentMessage


CACHE_TTL_HOURS = 24
MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

SYSTEM_PROMPT = """You are a fundamentals analyst for an options premium selling system. Given SEC filing excerpts, earnings data, and macro context for a stock, write a 3-5 sentence summary covering:
1. Financial health: revenue trend, profitability, debt levels
2. Recent developments: anything material from the latest filing
3. Risk factors relevant to selling options on this name
Be specific with numbers. No hedging language."""


class FundamentalsAnalyst:
    """On-demand fundamentals summaries for the Lead Agent."""

    def __init__(self, edgar_service=None, earnings_service=None,
                 fred_service=None, news_service=None):
        self.edgar = edgar_service
        self.earnings = earnings_service
        self.fred = fred_service
        self.news = news_service
        self._client = None
        self._enabled = False
        self._init_client()

    def _init_client(self):
        if not settings.together_api_key:
            logger.warning("[Fundamentals] Disabled — no TOGETHER_API_KEY")
            return
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url="https://api.together.xyz/v1",
            )
            self._enabled = True
        except Exception as e:
            logger.error(f"[Fundamentals] Client init failed: {e}")

    async def get_summary(self, symbol: str) -> dict:
        """
        Get a fundamentals summary for a symbol. Returns cached if fresh,
        otherwise generates via LLM.
        """
        symbol = symbol.upper()

        # Check cache
        cached = await self._get_cached(symbol)
        if cached:
            return {"symbol": symbol, "summary": cached, "source": "cache"}

        if not self._enabled:
            return {"symbol": symbol, "summary": "Fundamentals analysis unavailable (no API key)", "source": "disabled"}

        # Gather context
        context = await self._gather_context(symbol)
        if not context.strip():
            return {"symbol": symbol, "summary": "No fundamentals data available", "source": "no_data"}

        # LLM call
        try:
            response = await self._client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze {symbol}:\n\n{context}"},
                ],
                max_tokens=300,
                temperature=0.3,
            )
            summary = response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[Fundamentals] LLM call failed for {symbol}: {e}")
            return {"symbol": symbol, "summary": f"Analysis failed: {str(e)[:100]}", "source": "error"}

        # Cache the result
        await self._cache_summary(symbol, summary)

        return {"symbol": symbol, "summary": summary, "source": "fresh"}

    async def _gather_context(self, symbol: str) -> str:
        """Gather all available context for a symbol."""
        parts = []

        # EDGAR filing text
        if self.edgar:
            try:
                filings = await self.edgar.get_filing(symbol, "10-K", max_results=1)
                if not filings:
                    filings = await self.edgar.get_filing(symbol, "10-Q", max_results=1)
                if filings:
                    f = filings[0]
                    parts.append(f"Latest {f['filing_type']} filed {f.get('filed_date', '?')}, period {f.get('period_of_report', '?')}:")
                    text = await self.edgar.fetch_filing_text(f["url"], max_chars=8000)
                    if text:
                        parts.append(text[:3000])
            except Exception as e:
                logger.debug(f"[Fundamentals] EDGAR failed for {symbol}: {e}")

        # Earnings
        if self.earnings:
            try:
                info = await self.earnings.check_symbol(symbol)
                if info.get("event"):
                    parts.append(f"Next earnings: {info.get('event_date', '?')} ({info.get('days_until', '?')} days)")
            except Exception:
                pass

        # Macro snapshot
        if self.fred:
            try:
                macro = await self.fred.get_macro_indicators()
                vix = macro.get("vix_cboe", "?")
                t10 = macro.get("treasury_10y", "?")
                spread = macro.get("yield_curve_spread", "?")
                parts.append(f"Macro: VIX={vix}, 10Y={t10}%, yield curve spread={spread}")
            except Exception:
                pass

        # Recent news
        if self.news:
            try:
                headlines = await self.news.get_for_symbol(symbol, n=5)
                if headlines:
                    news_text = "; ".join(h.get("headline", "") for h in headlines[:3])
                    parts.append(f"Recent news: {news_text}")
            except Exception:
                pass

        return "\n\n".join(parts)

    async def _get_cached(self, symbol: str) -> Optional[str]:
        """Check agent_messages for a recent fundamentals summary."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AgentMessage.body)
                    .where(AgentMessage.sender == "Fundamentals-Analyst")
                    .where(AgentMessage.message_type == "fundamentals_summary")
                    .where(AgentMessage.subject == symbol)
                    .where(AgentMessage.timestamp >= cutoff)
                    .order_by(desc(AgentMessage.timestamp))
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                return row
        except Exception:
            return None

    async def _cache_summary(self, symbol: str, summary: str):
        """Write the summary to agent_messages for caching."""
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentMessage(
                    sender="Fundamentals-Analyst",
                    message_type="fundamentals_summary",
                    subject=symbol,
                    body=summary,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS),
                ))
                await session.commit()
        except Exception as e:
            logger.debug(f"[Fundamentals] Cache write failed for {symbol}: {e}")
