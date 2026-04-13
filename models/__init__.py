"""
Database Models — SQLAlchemy models for Premium Trader.

All models use SQLAlchemy 2.0 async-compatible style.
"""
from sqlalchemy.orm import declarative_base

# Shared Base for all models
Base = declarative_base()

# Import all models so Alembic can discover them
# Import order matters - Base must be defined first
from .trade import Trade
from .position import ActivePosition
from .performance import AgentPerformance
from .opportunity import ScannerOpportunity
from .journal_entry import JournalEntry
from .wheel_state import WheelStateRecord
from .proposal import TradeProposal
from .execution_log import ExecutionLog
from .regime_snapshot import RegimeSnapshot
from .earnings_event import EarningsEvent
from .performance_insight import PerformanceInsight
from .news_headline import NewsHeadline
from .playbook_entry import PlaybookEntry
from .strategy_insight import StrategyInsight
from .worker_state import WorkerState
from .equity_snapshot import EquitySnapshot
from .cycle_snapshot import CycleSnapshot
from .name_observation import NameObservation
from .agent_message import AgentMessage
from .skill_document import SkillDocument
from .reasoning_embedding import ReasoningEmbedding
from .agent_capability import AgentCapability
from .historical_bar import HistoricalBar
from .agent_action import AgentAction
from .macro_news_event import MacroNewsEvent
from .symbol_news_headline import SymbolNewsHeadline

__all__ = [
    "Base",
    "Trade",
    "ActivePosition",
    "AgentPerformance",
    "ScannerOpportunity",
    "JournalEntry",
    "WheelStateRecord",
    "TradeProposal",
    "ExecutionLog",
    "RegimeSnapshot",
    "EarningsEvent",
    "PerformanceInsight",
    "NewsHeadline",
    "PlaybookEntry",
    "StrategyInsight",
    "WorkerState",
    "EquitySnapshot",
    "CycleSnapshot",
    "NameObservation",
    "AgentMessage",
    "SkillDocument",
    "ReasoningEmbedding",
    "AgentCapability",
    "HistoricalBar",
    "AgentAction",
    "MacroNewsEvent",
    "SymbolNewsHeadline",
]
