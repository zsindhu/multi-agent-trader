"""
Pre-market Briefing Service — Assembles context for the Lead Agent's
morning cycle from the Research Analyst's reflection + active playbook.

Runs daily at 7:30 AM ET. NO LLM call — pure data assembly.
Cost: $0/month.

The briefing is stored in agent_messages and read by the Lead Agent
via the get_briefing tool.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, desc

from core.database import AsyncSessionLocal
from models.agent_message import AgentMessage
from models.playbook_entry import PlaybookEntry


class BriefingService:
    """Assembles the daily pre-market briefing from existing data."""

    async def generate_briefing(self, dry_run: bool = False) -> dict:
        """
        Build the pre-market briefing from:
        1. Latest Research Analyst reflection
        2. Active playbook entries (top 10 by confidence)
        """
        logger.info(f"[Briefing] Generating pre-market briefing (dry_run={dry_run})")

        parts = []

        # Research Analyst reflection
        reflection = await self._get_latest_reflection()
        if reflection:
            parts.append("## Research Analyst's Daily Reflection\n")
            parts.append(reflection)
        else:
            parts.append("## Research Analyst's Daily Reflection\n")
            parts.append("(No reflection available — Research Analyst may not have run yet)")

        # Active playbook entries
        playbook = await self._get_active_playbook(limit=10)
        if playbook:
            parts.append("\n## Active Playbook Entries (top 10 by confidence)\n")
            for entry in playbook:
                conf = entry.get("confidence", 0)
                parts.append(f"- [{entry['category']}] (confidence {conf:.1f}) {entry['content'][:200]}")

        briefing_text = "\n".join(parts)

        if dry_run:
            print(f"\n--- Pre-market Briefing ---\n{briefing_text}\n---")
            return {"generated": True, "dry_run": True, "length": len(briefing_text)}

        # Store in agent_messages
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentMessage(
                    sender="Pre-Market-Briefing",
                    message_type="daily_briefing",
                    subject=f"Briefing {datetime.now(timezone.utc).date().isoformat()}",
                    body=briefing_text,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=16),
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"[Briefing] Failed to store briefing: {e}")
            return {"error": str(e)}

        logger.info(f"[Briefing] Stored ({len(briefing_text)} chars)")
        return {"generated": True, "length": len(briefing_text)}

    async def get_today_briefing(self) -> Optional[str]:
        """Read today's briefing for the Lead Agent."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AgentMessage.body)
                    .where(AgentMessage.sender == "Pre-Market-Briefing")
                    .where(AgentMessage.message_type == "daily_briefing")
                    .where(AgentMessage.timestamp >= today_start)
                    .order_by(desc(AgentMessage.timestamp))
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception:
            return None

    async def _get_latest_reflection(self) -> Optional[str]:
        """Get the most recent Research Analyst reflection."""
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

    async def _get_active_playbook(self, limit: int = 10) -> list[dict]:
        """Get top active playbook entries by confidence."""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PlaybookEntry)
                    .where(PlaybookEntry.active == True)
                    .order_by(PlaybookEntry.confidence.desc().nullslast())
                    .limit(limit)
                )
                entries = result.scalars().all()
                return [
                    {
                        "category": e.category,
                        "content": e.content,
                        "confidence": e.confidence or 0.0,
                        "validated": e.validated,
                    }
                    for e in entries
                ]
        except Exception:
            return []
