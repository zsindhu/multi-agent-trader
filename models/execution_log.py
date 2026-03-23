"""ExecutionLog Model — Records every auto-executed trade with full reasoning context."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func

from models import Base


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    option_symbol = Column(String, nullable=True)
    action = Column(String, nullable=False)           # "open", "close", "roll"
    contract_type = Column(String, nullable=True)     # "call" or "put"
    strike = Column(Float, nullable=True)
    expiration = Column(String, nullable=True)
    delta = Column(Float, nullable=True)
    dte = Column(Integer, nullable=True)
    premium = Column(Float, nullable=True)            # per-share premium
    annualized_return = Column(Float, nullable=True)
    probability_of_profit = Column(Float, nullable=True)
    collateral_required = Column(Float, nullable=True)
    break_even_price = Column(Float, nullable=True)
    iv_rank_at_entry = Column(Float, nullable=True)
    scanner_score = Column(Float, nullable=True)
    stock_price_at_entry = Column(Float, nullable=True)
    rationale = Column(Text, nullable=False)
    order_id = Column(String, nullable=True)
    order_status = Column(String, nullable=True)      # "submitted", "filled", "rejected"
    fill_price = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True,
                        server_default=func.now())
