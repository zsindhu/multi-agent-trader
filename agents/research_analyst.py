"""
Research Analyst — Daily post-market reflection on the day's trading data.

Runs nightly at 5:30 PM ET. Reads the day's cycle_snapshots,
name_observations, trade_outcomes, and macro context. Produces a
narrative reflection (NOT prescriptive rules) that the pre-market
briefing injects into the Lead Agent's context the next morning.

This is the learning flywheel: data → reflection → briefing → better decisions.

CRITICAL CONSTRAINT: Produces NARRATIVE observations only.
"Energy names dominated promotions with gap z-scores" = good.
"Lower the gap z-score threshold to 1.5" = bad (that's the statistical
learner's job, gated behind outcome data).
"""
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, desc, func as sa_func

from config.settings import settings
from core.database import AsyncSessionLocal
from models.cycle_snapshot import CycleSnapshot
from models.name_observation import NameObservation
from models.trade_outcome import TradeOutcome
from models.agent_message import AgentMessage


MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

SYSTEM_PROMPT = """You are a Research Analyst for an automated options trading system. Your job is to reflect on today's trading activity and identify patterns, themes, and observations.

RULES:
- Write 3-5 paragraphs of NARRATIVE observations
- Be specific: mention symbol names, signal values, regime states
- DO NOT prescribe rule changes — that's the statistical learner's job
- DO NOT say "the system should lower/raise thresholds" — observations only
- DO identify: what names showed up repeatedly, what worked, what didn't, emerging themes
- DO note: sector patterns, regime observations, signal clustering

Your reflection will be read by the Lead Agent tomorrow morning as context for its decisions."""


class ResearchAnalyst:
    """Daily post-market reflection on trading patterns."""

    def __init__(self):
        self._client = None
        self._enabled = False
        self._init_client()

    def _init_client(self):
        if not settings.together_api_key:
            logger.warning("[Research] Disabled — no TOGETHER_API_KEY")
            return
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url="https://api.together.xyz/v1",
            )
            self._enabled = True
        except Exception as e:
            logger.error(f"[Research] Client init failed: {e}")

    async def run_reflection(self, dry_run: bool = False) -> dict:
        """Generate the daily reflection from today's data."""
        if not self._enabled:
            return {"skipped": True, "reason": "not_enabled"}

        logger.info(f"[Research] Starting daily reflection (dry_run={dry_run})")

        # Gather today's context
        context = await self._gather_daily_context()
        if not context.strip():
            logger.info("[Research] No data for today's reflection")
            return {"skipped": True, "reason": "no_data"}

        # Get yesterday's reflection for continuity
        prev_reflection = await self._get_previous_reflection()
        if prev_reflection:
            context += f"\n\n--- Yesterday's reflection (for continuity) ---\n{prev_reflection[:1000]}"

        # LLM call
        try:
            response = await self._client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Today's data:\n\n{context}"},
                ],
                max_tokens=800,
                temperature=0.4,
            )
            reflection = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[Research] LLM call failed: {e}")
            return {"error": str(e)}

        if dry_run:
            print(f"\n--- Research Analyst Reflection ---\n{reflection}\n---")
            return {"generated": True, "dry_run": True, "length": len(reflection)}

        # Store in agent_messages
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentMessage(
                    sender="Research-Analyst",
                    message_type="daily_reflection",
                    subject=f"Reflection {date.today().isoformat()}",
                    body=reflection,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"[Research] Failed to store reflection: {e}")
            return {"error": str(e)}

        logger.info(f"[Research] Reflection stored ({len(reflection)} chars)")
        return {"generated": True, "length": len(reflection)}

    async def _gather_daily_context(self) -> str:
        """Assemble today's data for the reflection."""
        parts = []
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Today's cycle snapshots
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(CycleSnapshot.summary, CycleSnapshot.regime, CycleSnapshot.vix_level,
                           CycleSnapshot.actions_decided, CycleSnapshot.actions_executed)
                    .where(CycleSnapshot.timestamp >= today_start)
                    .order_by(CycleSnapshot.timestamp)
                )
                cycles = result.all()
                if cycles:
                    parts.append(f"Lead Agent ran {len(cycles)} cycles today:")
                    for c in cycles:
                        parts.append(f"  Regime={c[1]}, VIX={c[2]}, decided={c[3]}, executed={c[4]}: {(c[0] or '')[:100]}")
        except Exception:
            pass

        # Top 20 Tier 2 promoted names (latest sweep only — append-only sweeps)
        try:
            from services.sweep_utils import latest_sweep_subq
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(
                        NameObservation.symbol, NameObservation.composite_score,
                        NameObservation.analysis, NameObservation.tier2b_reasoning,
                    )
                    .where(NameObservation.tier == 2)
                    .where(NameObservation.was_considered == True)
                    .where(NameObservation.timestamp >= today_start)
                    .where(NameObservation.sweep_id == latest_sweep_subq(2, today_start))
                    .order_by(NameObservation.composite_score.desc())
                    .limit(20)
                )
                promotions = result.all()
                if promotions:
                    parts.append(f"\nTop {len(promotions)} Tier 2 promotions:")
                    for p in promotions:
                        analysis = p[2] or {}
                        signals = analysis.get("signals", {})
                        firing = [n for n, s in signals.items() if s.get("fired")]
                        reasoning = (p[3] or analysis.get("tier2b_reasoning") or "")[:80]
                        parts.append(f"  {p[0]} score={p[1]:.3f} signals={','.join(firing)} — {reasoning}")
        except Exception:
            pass

        # Trade outcomes from today
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TradeOutcome)
                    .where(TradeOutcome.labeled_at >= today_start)
                )
                outcomes = list(result.scalars().all())
                if outcomes:
                    parts.append(f"\n{len(outcomes)} trade outcomes labeled today:")
                    for o in outcomes:
                        parts.append(f"  Trade #{o.trade_id}: {o.outcome}, PnL=${o.pnl_dollars or 0:.2f}, {o.holding_days or '?'}d, funnel={o.funnel_driven}")
        except Exception:
            pass

        return "\n".join(parts)

    async def _get_previous_reflection(self) -> Optional[str]:
        """Get yesterday's reflection for continuity."""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AgentMessage.body)
                    .where(AgentMessage.sender == "Research-Analyst")
                    .where(AgentMessage.message_type == "daily_reflection")
                    .order_by(desc(AgentMessage.timestamp))
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception:
            return None
