"""
Weekly Summarizer — Compresses a week of daily reflections, regime
observations, and trade outcomes into a single actionable digest.

Runs Sunday 6 PM ET. Writes a playbook entry with category="weekly_digest".
The Lead Agent reads these via the tiered playbook retrieval to get
temporal depth without raw bloat.

Model: Llama 3.3 70B on Together AI (~$0.01/week).
"""
from datetime import datetime, date, timedelta, timezone

from loguru import logger
from sqlalchemy import select, desc

from config.settings import settings
from core.database import AsyncSessionLocal
from models.agent_message import AgentMessage
from models.playbook_entry import PlaybookEntry
from models.trade_outcome import TradeOutcome
from models.trade import Trade


MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

SYSTEM_PROMPT = """You are a Weekly Summarizer for an automated options trading system. Your job is to compress this week's daily reflections, regime observations, and trade outcomes into a single actionable digest.

Your digest MUST include these sections:

1. **Week in Review** — Key regime changes, VIX movement, and market themes.

2. **Strategy Rules Applied** — Which strategy rules from the playbook were actually applied this week? Did they help or hurt? Be specific with trade references.

3. **New Patterns** — Any patterns you observe that are NOT yet captured in existing playbook entries. These are candidates for new strategy rules.

4. **Signal Contradictions** — Trades where the outcome contradicted the signal profile. If the signals said "trade this" but the outcome was a loss, or if a name was skipped but would have been profitable, call it out with specifics.

5. **Trade Outcomes** — Summary of all trades that closed this week: wins, losses, total PnL, average holding period.

6. **Watch List** — Names or themes to monitor next week based on this week's patterns.

RULES:
- Be specific: include symbol names, dollar amounts, signal names, dates
- Keep total length under 800 words
- This digest will be read by the Lead Agent for weeks — make it durable and actionable"""


class WeeklySummarizer:
    """Produces weekly digest from daily reflections + outcomes."""

    def __init__(self):
        self._client = None
        self._enabled = False
        self._init_client()

    def _init_client(self):
        if not settings.together_api_key:
            logger.warning("[Weekly] Disabled — no TOGETHER_API_KEY")
            return
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url="https://api.together.xyz/v1",
            )
            self._enabled = True
        except Exception as e:
            logger.error(f"[Weekly] Client init failed: {e}")

    async def run(self, dry_run: bool = False) -> dict:
        """Generate the weekly digest."""
        if not self._enabled:
            return {"skipped": True, "reason": "not_enabled"}

        logger.info(f"[Weekly] Starting weekly digest (dry_run={dry_run})")

        context = await self._gather_week_context()
        if not context.strip():
            logger.info("[Weekly] No data for weekly digest")
            return {"skipped": True, "reason": "no_data"}

        try:
            response = await self._client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"This week's data:\n\n{context}"},
                ],
                max_tokens=1200,
                temperature=0.3,
            )
            digest = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[Weekly] LLM call failed: {e}")
            return {"error": str(e)}

        if dry_run:
            print(f"\n--- Weekly Digest ---\n{digest}\n---")
            return {"generated": True, "dry_run": True, "length": len(digest)}

        # Store as playbook entry
        try:
            async with AsyncSessionLocal() as session:
                entry = PlaybookEntry(
                    category="weekly_digest",
                    content=digest,
                    source="weekly_summarizer",
                    confidence=0.7,
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
                            text=f"[weekly_digest] {digest}",
                            source_table="playbook_entries",
                            source_id=entry.id,
                        )
                except Exception:
                    pass

                logger.info(f"[Weekly] Digest stored (id={entry.id}, {len(digest)} chars)")
                return {"generated": True, "id": entry.id, "length": len(digest)}
        except Exception as e:
            logger.error(f"[Weekly] Failed to store digest: {e}")
            return {"error": str(e)}

    async def _gather_week_context(self) -> str:
        """Assemble the past week's data for summarization."""
        parts = []
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        # Daily reflections from this week
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AgentMessage.subject, AgentMessage.body)
                    .where(AgentMessage.sender == "Research-Analyst")
                    .where(AgentMessage.message_type == "daily_reflection")
                    .where(AgentMessage.timestamp >= week_ago)
                    .order_by(AgentMessage.timestamp)
                )
                reflections = result.all()
                if reflections:
                    parts.append(f"=== {len(reflections)} Daily Reflections ===")
                    for r in reflections:
                        parts.append(f"\n--- {r[0]} ---\n{r[1]}")
        except Exception:
            pass

        # Regime observations from this week
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PlaybookEntry.content, PlaybookEntry.created_at)
                    .where(PlaybookEntry.category == "regime_observation")
                    .where(PlaybookEntry.active == True)
                    .where(PlaybookEntry.created_at >= week_ago)
                    .order_by(PlaybookEntry.created_at)
                )
                regimes = result.all()
                if regimes:
                    parts.append(f"\n=== {len(regimes)} Regime Observations ===")
                    for r in regimes:
                        parts.append(f"  [{r[1].strftime('%a %m/%d')}] {r[0][:200]}")
        except Exception:
            pass

        # Active strategy rules (for the "rules applied" section)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PlaybookEntry.content)
                    .where(PlaybookEntry.category == "strategy_rule")
                    .where(PlaybookEntry.active == True)
                    .order_by(PlaybookEntry.confidence.desc())
                    .limit(20)
                )
                rules = result.all()
                if rules:
                    parts.append(f"\n=== {len(rules)} Active Strategy Rules ===")
                    for r in rules:
                        parts.append(f"  - {r[0][:200]}")
        except Exception:
            pass

        # Trade outcomes from this week
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TradeOutcome, Trade.symbol)
                    .join(Trade, TradeOutcome.trade_id == Trade.id)
                    .where(TradeOutcome.labeled_at >= week_ago)
                    .order_by(TradeOutcome.labeled_at)
                )
                rows = result.all()
                if rows:
                    parts.append(f"\n=== {len(rows)} Trade Outcomes This Week ===")
                    for outcome, symbol in rows:
                        profile_summary = ""
                        if outcome.signal_profile:
                            signals = outcome.signal_profile.get("signals", {})
                            fired = [n for n, s in signals.items() if s.get("fired")]
                            if fired:
                                profile_summary = f" signals=[{','.join(fired)}]"
                        parts.append(
                            f"  {symbol}: {outcome.outcome} PnL=${outcome.pnl_dollars or 0:.2f} "
                            f"held {outcome.holding_days or '?'}d funnel={outcome.funnel_driven}"
                            f"{profile_summary}"
                        )
        except Exception:
            pass

        return "\n".join(parts)
