"""
Trade Journal Agent — Observes and records all trades with maximum granularity.

Doesn't trade. Observes worker agents and captures:
- Trade details (entry and exit)
- Market context at entry/exit
- Strategy context
- Performance metrics

Provides aggregated views for analysis.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, Integer
from sqlalchemy.orm import selectinload
from loguru import logger

from agents.base_agent import BaseAgent
from models.journal_entry import JournalEntry
from models.position import ActivePosition
from core.database import AsyncSessionLocal


class TradeJournalAgent(BaseAgent):
    """
    Trade Journal Agent — Records all trades with full context.
    
    Observes worker agents and logs:
    - Entry: trade details, market context, strategy context
    - Exit: exit context, realized P&L, performance metrics
    """
    
    def __init__(self):
        super().__init__(name="Trade-Journal", agent_type="observer")
        self._pending_entries: Dict[str, JournalEntry] = {}  # option_symbol -> entry
    
    async def scan(self) -> list[dict]:
        """Trade Journal doesn't scan for opportunities."""
        return []
    
    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        """Trade Journal doesn't evaluate opportunities."""
        return []
    
    async def execute(self, trades: list[dict]) -> list[dict]:
        """Trade Journal doesn't execute trades."""
        return []
    
    async def manage_positions(self) -> list[dict]:
        """Trade Journal doesn't manage positions."""
        return []
    
    # ── Trade Logging Methods ───────────────────────────────────────────
    
    async def log_entry(
        self,
        agent_name: str,
        symbol: str,
        option_symbol: str,
        contract_type: str,
        strike: float,
        expiration: str,
        side: str,
        quantity: int,
        fill_price: float,
        premium: Optional[float] = None,
        # Market context
        iv_rank: Optional[float] = None,
        stock_price: Optional[float] = None,
        vix_level: Optional[float] = None,
        distance_from_support: Optional[float] = None,
        distance_from_20ma: Optional[float] = None,
        distance_from_50ma: Optional[float] = None,
        scanner_composite_score: Optional[float] = None,
        sector: Optional[str] = None,
        # Strategy context
        delta_at_entry: Optional[float] = None,
        dte_at_entry: Optional[int] = None,
        annualized_return_at_entry: Optional[float] = None,
        probability_of_profit: Optional[float] = None,
    ) -> JournalEntry:
        """
        Log a trade entry with full context.
        
        Returns the created JournalEntry.
        """
        async with AsyncSessionLocal() as session:
            entry = JournalEntry(
                agent_name=agent_name,
                symbol=symbol,
                option_symbol=option_symbol,
                contract_type=contract_type,
                strike=strike,
                expiration=expiration,
                side=side,
                quantity=quantity,
                fill_price=fill_price,
                premium=premium,
                # Entry context
                entry_iv_rank=iv_rank,
                entry_stock_price=stock_price,
                entry_vix_level=vix_level,
                entry_distance_from_support=distance_from_support,
                entry_distance_from_20ma=distance_from_20ma,
                entry_distance_from_50ma=distance_from_50ma,
                entry_scanner_composite_score=scanner_composite_score,
                entry_sector=sector,
                # Strategy context
                delta_at_entry=delta_at_entry,
                dte_at_entry=dte_at_entry,
                annualized_return_at_entry=annualized_return_at_entry,
                probability_of_profit=probability_of_profit,
                # Timestamps
                entry_at=datetime.utcnow(),
            )
            
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            
            # Store for exit logging
            self._pending_entries[option_symbol] = entry
            
            logger.info(
                f"[Trade Journal] Entry logged: {agent_name} {side.upper()} {quantity}x "
                f"{option_symbol} @ ${fill_price:.2f}"
            )
            
            return entry
    
    async def log_exit(
        self,
        option_symbol: str,
        exit_stock_price: Optional[float] = None,
        exit_iv_rank: Optional[float] = None,
        exit_reason: Optional[str] = None,
        realized_pnl: Optional[float] = None,
        days_held: Optional[int] = None,
    ) -> Optional[JournalEntry]:
        """
        Log a trade exit and compute performance metrics.
        
        Args:
            option_symbol: Option symbol to close
            exit_stock_price: Stock price at exit
            exit_iv_rank: IV rank at exit
            exit_reason: "profit_target", "stop_loss", "expired", "assigned", "rolled"
            realized_pnl: Realized profit/loss
            days_held: Number of days position was held
        
        Returns:
            Updated JournalEntry or None if entry not found
        """
        async with AsyncSessionLocal() as session:
            # Find the entry
            stmt = select(JournalEntry).where(
                JournalEntry.option_symbol == option_symbol,
                JournalEntry.exit_at.is_(None)
            ).order_by(JournalEntry.entry_at.desc())
            
            result = await session.execute(stmt)
            entry = result.scalar_one_or_none()
            
            if not entry:
                logger.warning(f"[Trade Journal] No open entry found for {option_symbol}")
                return None
            
            # Update exit fields
            entry.exit_stock_price = exit_stock_price
            entry.exit_iv_rank = exit_iv_rank
            entry.exit_reason = exit_reason
            entry.realized_pnl = realized_pnl
            entry.days_held = days_held
            entry.exit_at = datetime.utcnow()
            
            # Calculate return %
            if entry.premium and entry.premium > 0:
                entry.return_pct = (realized_pnl / entry.premium) * 100 if realized_pnl else None
            
            await session.commit()
            await session.refresh(entry)
            
            # Remove from pending
            self._pending_entries.pop(option_symbol, None)
            
            logger.info(
                f"[Trade Journal] Exit logged: {option_symbol} - "
                f"P&L: ${realized_pnl:.2f}, Reason: {exit_reason}"
            )
            
            return entry
    
    # ── Aggregated Views ─────────────────────────────────────────────────
    
    async def get_symbol_stats(self, symbol: str) -> dict:
        """
        Get aggregated statistics for a symbol.
        
        Returns:
            Dict with win_rate, total_trades, avg_premium, avg_return, etc.
        """
        async with AsyncSessionLocal() as session:
            stmt = select(
                func.count(JournalEntry.id).label("total_trades"),
                func.sum(func.cast(JournalEntry.realized_pnl > 0, Integer)).label("wins"),
                func.sum(func.cast(JournalEntry.realized_pnl < 0, Integer)).label("losses"),
                func.avg(JournalEntry.premium).label("avg_premium"),
                func.sum(JournalEntry.realized_pnl).label("total_pnl"),
                func.avg(JournalEntry.realized_pnl).label("avg_pnl"),
                func.avg(JournalEntry.days_held).label("avg_days_held"),
            ).where(
                JournalEntry.symbol == symbol,
                JournalEntry.exit_at.isnot(None)
            )
            
            result = await session.execute(stmt)
            row = result.first()
            
            if not row or row.total_trades == 0:
                return {
                    "symbol": symbol,
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_premium": 0.0,
                    "avg_return": 0.0,
                    "avg_days_held": 0.0,
                }
            
            win_rate = (row.wins / row.total_trades * 100) if row.total_trades > 0 else 0.0
            
            return {
                "symbol": symbol,
                "total_trades": row.total_trades,
                "wins": row.wins,
                "losses": row.losses,
                "win_rate": round(win_rate, 2),
                "total_pnl": float(row.total_pnl or 0),
                "avg_pnl": float(row.avg_pnl or 0),
                "avg_premium": float(row.avg_premium or 0),
                "avg_return": float(row.avg_pnl / row.avg_premium * 100) if row.avg_premium else 0.0,
                "avg_days_held": float(row.avg_days_held or 0),
            }
    
    async def get_strategy_stats(
        self,
        agent_name: str,
        delta_min: Optional[float] = None,
        delta_max: Optional[float] = None,
    ) -> dict:
        """
        Get aggregated statistics for a strategy (agent) with optional delta filter.
        
        Example: "CSPs at -0.20 to -0.25 delta win 78%"
        
        Returns:
            Dict with win_rate, total_trades, avg_premium, etc.
        """
        async with AsyncSessionLocal() as session:
            conditions = [
                JournalEntry.agent_name == agent_name,
                JournalEntry.exit_at.isnot(None)
            ]
            
            if delta_min is not None:
                conditions.append(JournalEntry.delta_at_entry >= delta_min)
            if delta_max is not None:
                conditions.append(JournalEntry.delta_at_entry <= delta_max)
            
            stmt = select(
                func.count(JournalEntry.id).label("total_trades"),
                func.sum(func.cast(JournalEntry.realized_pnl > 0, Integer)).label("wins"),
                func.sum(func.cast(JournalEntry.realized_pnl < 0, Integer)).label("losses"),
                func.avg(JournalEntry.premium).label("avg_premium"),
                func.sum(JournalEntry.realized_pnl).label("total_pnl"),
                func.avg(JournalEntry.realized_pnl).label("avg_pnl"),
                func.avg(JournalEntry.delta_at_entry).label("avg_delta"),
            ).where(and_(*conditions))
            
            result = await session.execute(stmt)
            row = result.first()
            
            if not row or row.total_trades == 0:
                return {
                    "agent_name": agent_name,
                    "delta_range": f"{delta_min} to {delta_max}" if delta_min and delta_max else "all",
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_premium": 0.0,
                }
            
            win_rate = (row.wins / row.total_trades * 100) if row.total_trades > 0 else 0.0
            
            return {
                "agent_name": agent_name,
                "delta_range": f"{delta_min} to {delta_max}" if delta_min and delta_max else "all",
                "total_trades": row.total_trades,
                "wins": row.wins,
                "losses": row.losses,
                "win_rate": round(win_rate, 2),
                "total_pnl": float(row.total_pnl or 0),
                "avg_pnl": float(row.avg_pnl or 0),
                "avg_premium": float(row.avg_premium or 0),
                "avg_delta": float(row.avg_delta or 0),
            }
    
    async def get_full_journal(
        self,
        agent_name: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[JournalEntry]:
        """
        Get full journal entries with filters.
        
        Args:
            agent_name: Filter by agent
            symbol: Filter by symbol
            limit: Maximum number of entries to return
        
        Returns:
            List of JournalEntry objects
        """
        async with AsyncSessionLocal() as session:
            conditions = []
            
            if agent_name:
                conditions.append(JournalEntry.agent_name == agent_name)
            if symbol:
                conditions.append(JournalEntry.symbol == symbol)
            
            stmt = select(JournalEntry)
            if conditions:
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(JournalEntry.entry_at.desc()).limit(limit)
            
            result = await session.execute(stmt)
            return list(result.scalars().all())
