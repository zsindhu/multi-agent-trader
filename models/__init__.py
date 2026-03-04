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

__all__ = ["Base", "Trade", "ActivePosition", "AgentPerformance", "ScannerOpportunity", "JournalEntry"]
