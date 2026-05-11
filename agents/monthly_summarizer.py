"""
Monthly Summarizer — Compresses weekly digests + monthly trade data into
a single long-horizon summary.

Runs 1st of each month at 6:30 PM ET. Writes a playbook entry with
category="monthly_digest". The Lead Agent reads these via the tiered
playbook retrieval for long-term pattern awareness.

Model: Llama 3.3 70B on Together AI (~$0.02/month).
"""
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, func as sa_func

from config.settings import settings
from core.database import AsyncSessionLocal
from models.playbook_entry import PlaybookEntry
from models.trade_outcome import TradeOutcome
from models.trade import Trade
from models.cycle_snapshot import CycleSnapshot


MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

SYSTEM_PROMPT = """You are a Monthly Summarizer for an automated options trading system. Your job is to compress this month's weekly digests and trade data into a single durable summary.

Your summary MUST include:

1. **Month Overview** — Market regime trajectory, major regime changes, key themes.

2. **Performance Summary** — Total trades, win rate, PnL, profit factor, average holding period. Compare to previous months if data is available.

3. **Strategy Evolution** — What strategy rules were added, validated, or invalidated this month? What did the system learn?

4. **Persistent Patterns** — Patterns that appeared across multiple weeks (not one-offs). These are the most valuable signals for long-term strategy development.

5. **Next Month Focus** — Based on this month's data, what should the system prioritize?

RULES:
- Be specific: include numbers, dates, symbol names
- Keep total length under 600 words
- This summary may be read months from now — write for durability, not recency
- Focus on what CHANGED this month, not what stayed the same"""


class MonthlySummarizer:
    """Produces monthly digest from weekly digests + trade data."""

    def __init__(self):
        self._client = None
        self._enabled = False
        self._init_client()

    def _init_client(self):
        if not settings.together_api_key:
            logger.warning("[Monthly] Disabled — no TOGETHER_API_KEY")
            return
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url="https://api.together.xyz/v1",
            )
            self._enabled = True
        except Exception as e:
            logger.error(f"[Monthly] Client init failed: {e}")

    async def run(self, dry_run: bool = False) -> dict:
        """Generate the monthly digest."""
        if not self._enabled:
            return {"skipped": True, "reason": "not_enabled"}

        logger.info(f"[Monthly] Starting monthly digest (dry_run={dry_run})")

        context = await self._gather_month_context()
        if not context.strip():
            logger.info("[Monthly] No data for monthly digest")
            return {"skipped": True, "reason": "no_data"}

        try:
            response = await self._client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"This month's data:\n\n{context}"},
                ],
                max_tokens=1000,
                temperature=0.3,
            )
            digest = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[Monthly] LLM call failed: {e}")
            return {"error": str(e)}

        if dry_run:
            print(f"\n--- Monthly Digest ---\n{digest}\n---")
            return {"generated": True, "dry_run": True, "length": len(digest)}

        # Store as playbook entry
        try:
            async with AsyncSessionLocal() as session:
                entry = PlaybookEntry(
                    category="monthly_digest",
                    content=digest,
                    source="monthly_summarizer",
                    confidence=0.8,
                )
                session.add(entry)
                await session.commit()
                await session.refresh(entry)

                # Embed for semantic retrieval
                try:
                    from services.embeddings import EmbeddingsService
                    emb = EmbeddingsService()
                    if emb.is_enabled:
                        await emb.embed_and_store(
                            text=f"[monthly_digest] {digest}",
                            source_table="playbook_entries",
                            source_id=entry.id,
                        )
                except Exception:
                    pass

                logger.info(f"[Monthly] Digest stored (id={entry.id}, {len(digest)} chars)")
                return {"generated": True, "id": entry.id, "length": len(digest)}
        except Exception as e:
            logger.error(f"[Monthly] Failed to store digest: {e}")
            return {"error": str(e)}

    async def _gather_month_context(self) -> str:
        """Assemble the past month's data for summarization."""
        parts = []
        month_ago = datetime.now(timezone.utc) - timedelta(days=31)

        # Weekly digests from this month
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PlaybookEntry.content, PlaybookEntry.created_at)
                    .where(PlaybookEntry.category == "weekly_digest")
                    .where(PlaybookEntry.active == True)
                    .where(PlaybookEntry.created_at >= month_ago)
                    .order_by(PlaybookEntry.created_at)
                )
                digests = result.all()
                if digests:
                    parts.append(f"=== {len(digests)} Weekly Digests ===")
                    for d in digests:
                        parts.append(f"\n--- Week of {d[1].strftime('%Y-%m-%d')} ---\n{d[0]}")
        except Exception:
            pass

        # Monthly trade outcome aggregates
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TradeOutcome, Trade.symbol)
                    .join(Trade, TradeOutcome.trade_id == Trade.id)
                    .where(TradeOutcome.labeled_at >= month_ago)
                    .order_by(TradeOutcome.labeled_at)
                )
                rows = result.all()
                if rows:
                    wins = [o for o, _ in rows if o.outcome == "win"]
                    losses = [o for o, _ in rows if o.outcome == "loss"]
                    total_pnl = sum(o.pnl_dollars or 0 for o, _ in rows)
                    parts.append(f"\n=== Trade Outcomes ({len(rows)} total) ===")
                    parts.append(f"Wins: {len(wins)}, Losses: {len(losses)}, "
                                 f"Win rate: {len(wins)/len(rows)*100:.0f}%")
                    parts.append(f"Total PnL: ${total_pnl:.2f}")
                    if wins:
                        parts.append(f"Avg win: ${sum(o.pnl_dollars or 0 for o in wins)/len(wins):.2f}")
                    if losses:
                        parts.append(f"Avg loss: ${sum(o.pnl_dollars or 0 for o in losses)/len(losses):.2f}")
                    parts.append("\nIndividual trades:")
                    for outcome, symbol in rows:
                        parts.append(
                            f"  {symbol}: {outcome.outcome} ${outcome.pnl_dollars or 0:.2f} "
                            f"held {outcome.holding_days or '?'}d"
                        )
        except Exception:
            pass

        # Regime trajectory (cycle snapshots summary)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(
                        sa_func.date_trunc('day', CycleSnapshot.timestamp).label('day'),
                        sa_func.avg(CycleSnapshot.vix_level),
                        sa_func.mode().within_group(CycleSnapshot.regime),
                    )
                    .where(CycleSnapshot.timestamp >= month_ago)
                    .group_by('day')
                    .order_by('day')
                )
                days = result.all()
                if days:
                    parts.append(f"\n=== Regime Trajectory ({len(days)} trading days) ===")
                    for day, avg_vix, regime in days:
                        parts.append(f"  {day}: regime={regime}, avg_vix={avg_vix:.1f}" if avg_vix else f"  {day}: regime={regime}")
        except Exception:
            pass

        return "\n".join(parts)
