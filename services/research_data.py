"""
Research Data Service — Write and read interfaces for the research data layer.

This module is the canonical way for agents to interact with the new
research tables. It hides the SQLAlchemy details and provides clean,
typed methods for the operations agents actually need.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from loguru import logger
from sqlalchemy import select, desc

from core.database import AsyncSessionLocal
from models.cycle_snapshot import CycleSnapshot
from models.name_observation import NameObservation
from models.agent_message import AgentMessage
from models.skill_document import SkillDocument
from models.agent_capability import AgentCapability


class ResearchDataService:
    """High-level interface to the research data layer."""

    # ── Cycle snapshots ────────────────────────────────────────

    async def write_cycle_snapshot(
        self,
        regime: Optional[str] = None,
        regime_confidence: Optional[float] = None,
        vix_level: Optional[float] = None,
        vix_direction: Optional[str] = None,
        breadth_pct: Optional[float] = None,
        spy_trend: Optional[str] = None,
        credit_stress: Optional[str] = None,
        equity: Optional[float] = None,
        cash: Optional[float] = None,
        buying_power: Optional[float] = None,
        open_positions_count: Optional[int] = None,
        unrealized_pnl: Optional[float] = None,
        actions_decided: Optional[int] = None,
        actions_executed: Optional[int] = None,
        summary: Optional[str] = None,
        reasoning: Optional[str] = None,
        llm_tokens_in: Optional[int] = None,
        llm_tokens_out: Optional[int] = None,
        llm_cost_usd: Optional[float] = None,
        llm_model: Optional[str] = None,
        full_context: Optional[dict] = None,
    ) -> Optional[int]:
        """Write a new cycle snapshot. Returns the new row's ID."""
        try:
            async with AsyncSessionLocal() as session:
                snap = CycleSnapshot(
                    regime=regime,
                    regime_confidence=regime_confidence,
                    vix_level=vix_level,
                    vix_direction=vix_direction,
                    breadth_pct=breadth_pct,
                    spy_trend=spy_trend,
                    credit_stress=credit_stress,
                    equity=equity,
                    cash=cash,
                    buying_power=buying_power,
                    open_positions_count=open_positions_count,
                    unrealized_pnl=unrealized_pnl,
                    actions_decided=actions_decided,
                    actions_executed=actions_executed,
                    summary=summary,
                    reasoning=reasoning,
                    llm_tokens_in=llm_tokens_in,
                    llm_tokens_out=llm_tokens_out,
                    llm_cost_usd=llm_cost_usd,
                    llm_model=llm_model,
                    full_context=full_context,
                )
                session.add(snap)
                await session.commit()
                await session.refresh(snap)
                return snap.id
        except Exception as e:
            logger.error(f"[ResearchData] write_cycle_snapshot failed: {e}")
            return None

    async def get_recent_cycles(self, limit: int = 10) -> list:
        """Return the most recent cycle snapshots."""
        async with AsyncSessionLocal() as session:
            stmt = select(CycleSnapshot).order_by(desc(CycleSnapshot.timestamp)).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Agent messages ─────────────────────────────────────────

    async def post_message(
        self,
        sender: str,
        message_type: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        payload: Optional[dict] = None,
        recipient: Optional[str] = None,
        ttl_hours: Optional[int] = 24,
    ) -> Optional[int]:
        """Post a message to the agent message bus. Returns the new row's ID."""
        try:
            expires_at = None
            if ttl_hours is not None:
                expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            async with AsyncSessionLocal() as session:
                msg = AgentMessage(
                    sender=sender,
                    recipient=recipient,
                    message_type=message_type,
                    subject=subject,
                    body=body,
                    payload=payload,
                    expires_at=expires_at,
                )
                session.add(msg)
                await session.commit()
                await session.refresh(msg)
                return msg.id
        except Exception as e:
            logger.error(f"[ResearchData] post_message failed: {e}")
            return None

    async def get_unread_messages_for_lead(self, limit: int = 20) -> list:
        """Return messages the Lead Agent hasn't read yet, newest first."""
        async with AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)
            stmt = (
                select(AgentMessage)
                .where(AgentMessage.read_by_lead_agent == False)
                .where(
                    (AgentMessage.expires_at == None) |
                    (AgentMessage.expires_at > now)
                )
                .order_by(desc(AgentMessage.timestamp))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def mark_messages_read_by_lead(self, message_ids: list[int]) -> None:
        """Mark messages as read by the Lead Agent."""
        if not message_ids:
            return
        async with AsyncSessionLocal() as session:
            stmt = select(AgentMessage).where(AgentMessage.id.in_(message_ids))
            result = await session.execute(stmt)
            for msg in result.scalars().all():
                msg.read_by_lead_agent = True
            await session.commit()

    # ── Skill documents ────────────────────────────────────────

    async def get_current_skill_doc(self, agent_name: str) -> Optional[SkillDocument]:
        """Return the latest version of an agent's skill document."""
        async with AsyncSessionLocal() as session:
            stmt = (
                select(SkillDocument)
                .where(SkillDocument.agent_name == agent_name)
                .order_by(desc(SkillDocument.version))
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_skill_doc(
        self,
        agent_name: str,
        title: str,
        content: str,
        summary: str,
        created_by: str,
    ) -> Optional[int]:
        """Append a new version of an agent's skill document. Returns the new version number."""
        try:
            current = await self.get_current_skill_doc(agent_name)
            new_version = (current.version + 1) if current else 1
            async with AsyncSessionLocal() as session:
                doc = SkillDocument(
                    agent_name=agent_name,
                    version=new_version,
                    title=title,
                    content=content,
                    summary=summary,
                    created_by=created_by,
                )
                session.add(doc)
                await session.commit()
                return new_version
        except Exception as e:
            logger.error(f"[ResearchData] update_skill_doc failed: {e}")
            return None

    # ── Agent capabilities ─────────────────────────────────────

    async def register_agent(
        self,
        agent_name: str,
        agent_type: str,
        capabilities: list[str],
        description: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        """Register or update an agent's capability entry."""
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(AgentCapability).where(AgentCapability.agent_name == agent_name)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                if existing:
                    existing.agent_type = agent_type
                    existing.capabilities = capabilities
                    existing.description = description
                    existing.config = config
                    existing.is_active = True
                else:
                    cap = AgentCapability(
                        agent_name=agent_name,
                        agent_type=agent_type,
                        capabilities=capabilities,
                        description=description,
                        config=config,
                        is_active=True,
                    )
                    session.add(cap)
                await session.commit()
        except Exception as e:
            logger.error(f"[ResearchData] register_agent failed: {e}")

    async def get_active_agents(self) -> list:
        """Return all currently active agents."""
        async with AsyncSessionLocal() as session:
            stmt = select(AgentCapability).where(AgentCapability.is_active == True)
            result = await session.execute(stmt)
            return list(result.scalars().all())
