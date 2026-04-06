"""
CycleSnapshot — Full system state captured at every Lead Agent cycle.

The structured columns enable fast queries ("show me cycles where VIX > 30
and regime was risk-off"). The full_context JSONB column captures
everything else (tool calls, tool results, full reasoning, playbook entries
read, playbook entries written) for deep inspection and replay.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy import JSON
from sqlalchemy.sql import func

from models import Base


class CycleSnapshot(Base):
    __tablename__ = "cycle_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)

    # ── Regime context ─────────────────────────────────────────
    regime = Column(String(32), index=True)
    regime_confidence = Column(Float)
    vix_level = Column(Float)
    vix_direction = Column(String(16))
    breadth_pct = Column(Float)
    spy_trend = Column(String(16))
    credit_stress = Column(String(8))

    # ── Portfolio state ────────────────────────────────────────
    equity = Column(Float)
    cash = Column(Float)
    buying_power = Column(Float)
    open_positions_count = Column(Integer)
    unrealized_pnl = Column(Float)

    # ── Cycle outcomes ─────────────────────────────────────────
    actions_decided = Column(Integer)
    actions_executed = Column(Integer)
    summary = Column(Text)
    reasoning = Column(Text)

    # ── LLM cost tracking ──────────────────────────────────────
    llm_tokens_in = Column(Integer)
    llm_tokens_out = Column(Integer)
    llm_cost_usd = Column(Float)
    llm_model = Column(String(64))

    # ── Full context blob ──────────────────────────────────────
    full_context = Column(JSON)
