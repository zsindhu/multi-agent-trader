"""
Performance Logger — Aggregates trade data, computes agent metrics.

Uses async SQLAlchemy sessions to query the database.
Provides metrics for Lead Agent decision-making.
"""
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import selectinload
from loguru import logger

from core.database import AsyncSessionLocal
from models.trade import Trade
from models.position import ActivePosition
from models.performance import AgentPerformance


class PerformanceLogger:
    """Performance logger with async SQLAlchemy database operations."""
    
    def __init__(self):
        self.cycle_history = []
    
    async def log_trade(
        self,
        agent_name: str,
        symbol: str,
        option_symbol: Optional[str],
        trade_type: str,
        side: str,
        quantity: int,
        price: float,
        premium: Optional[float] = None,
        strike: Optional[float] = None,
        expiration: Optional[str] = None,
        status: str = "filled",
        pnl: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Trade:
        """Record a trade execution to the database."""
        async with AsyncSessionLocal() as session:
            trade = Trade(
                agent_name=agent_name,
                symbol=symbol,
                option_symbol=option_symbol,
                trade_type=trade_type,
                side=side,
                quantity=quantity,
                price=price,
                premium=premium,
                strike=strike,
                expiration=expiration,
                status=status,
                pnl=pnl,
                notes=notes,
            )
            session.add(trade)
            await session.commit()
            await session.refresh(trade)
            
            logger.info(f"[Logger] Trade logged: {agent_name} {side} {quantity}x {symbol} @ ${price:.2f}")
            return trade
    
    async def log_position_update(
        self,
        agent_name: str,
        option_symbol: str,
        current_price: Optional[float] = None,
        status: Optional[str] = None,
        pnl: Optional[float] = None,
    ) -> Optional[ActivePosition]:
        """Update an existing position or create a new one."""
        async with AsyncSessionLocal() as session:
            # Find existing position
            stmt = select(ActivePosition).where(
                ActivePosition.option_symbol == option_symbol,
                ActivePosition.agent_name == agent_name
            )
            result = await session.execute(stmt)
            position = result.scalar_one_or_none()
            
            if position:
                # Update existing
                if current_price is not None:
                    position.current_price = current_price
                if status is not None:
                    position.status = status
                if pnl is not None:
                    position.pnl = pnl
                if status in ["closed", "assigned", "expired"]:
                    position.closed_at = datetime.utcnow()
                
                await session.commit()
                await session.refresh(position)
                logger.debug(f"[Logger] Position updated: {option_symbol}")
            else:
                logger.warning(f"[Logger] Position not found for update: {option_symbol}")
            
            return position
    
    async def log_cycle(self, results: dict):
        """Log a cycle execution summary (kept for backward compatibility)."""
        entry = {"timestamp": datetime.utcnow().isoformat(), "agents": {}}
        for agent_name, result in results.items():
            entry["agents"][agent_name] = {
                "trades_executed": len(result.get("new_trades", [])),
                "position_actions": len(result.get("position_actions", [])),
            }
        self.cycle_history.append(entry)
        logger.info(f"[Logger] Cycle logged: {len(results)} agents reported.")
    
    async def get_agent_metrics(self, agent_name: str, lookback_days: int = 30) -> dict:
        """
        Query database and compute agent metrics.
        
        Returns:
            Dict with: win_rate, total_premium_collected, avg_days_held,
            avg_return_per_trade, sharpe_ratio, max_drawdown
        """
        async with AsyncSessionLocal() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
            
            # Get closed trades
            stmt = select(Trade).where(
                Trade.agent_name == agent_name,
                Trade.closed_at.isnot(None),
                Trade.closed_at >= cutoff_date
            )
            result = await session.execute(stmt)
            trades = list(result.scalars().all())
            
            if not trades:
                return {
                    "agent": agent_name,
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_premium": 0.0,
                    "avg_days_held": 0.0,
                    "avg_return_per_trade": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                }
            
            # Calculate metrics
            total_trades = len(trades)
            wins = sum(1 for t in trades if t.pnl and t.pnl > 0)
            losses = sum(1 for t in trades if t.pnl and t.pnl < 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
            
            total_premium = sum(t.premium or 0 for t in trades)
            total_pnl = sum(t.pnl or 0 for t in trades)
            avg_return_per_trade = total_pnl / total_trades if total_trades > 0 else 0.0
            
            # Calculate days held (simplified - use created_at to closed_at)
            days_held_list = []
            for t in trades:
                if t.created_at and t.closed_at:
                    days = (t.closed_at - t.created_at).days
                    days_held_list.append(days)
            avg_days_held = sum(days_held_list) / len(days_held_list) if days_held_list else 0.0
            
            # Sharpe ratio (simplified - would need daily returns for proper calculation)
            returns = [t.pnl or 0 for t in trades]
            if len(returns) > 1:
                mean_return = sum(returns) / len(returns)
                variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
                std_dev = variance ** 0.5
                sharpe_ratio = (mean_return / std_dev * (252 ** 0.5)) if std_dev > 0 else 0.0
            else:
                sharpe_ratio = 0.0
            
            # Max drawdown (simplified - would need equity curve)
            pnl_list = [t.pnl or 0 for t in trades]
            cumulative = []
            running_total = 0
            for pnl in pnl_list:
                running_total += pnl
                cumulative.append(running_total)
            
            if cumulative:
                peak = cumulative[0]
                max_dd = 0.0
                for value in cumulative:
                    if value > peak:
                        peak = value
                    dd = (peak - value) / peak if peak > 0 else 0.0
                    max_dd = max(max_dd, dd)
            else:
                max_dd = 0.0
            
            return {
                "agent": agent_name,
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "total_premium_collected": round(total_premium, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_days_held": round(avg_days_held, 1),
                "avg_return_per_trade": round(avg_return_per_trade, 2),
                "sharpe_ratio": round(sharpe_ratio, 2),
                "max_drawdown": round(max_dd * 100, 2),  # As percentage
            }
    
    async def get_portfolio_summary(self) -> dict:
        """Aggregate metrics across all agents."""
        async with AsyncSessionLocal() as session:
            # Get all unique agents
            stmt = select(Trade.agent_name).distinct()
            result = await session.execute(stmt)
            agents = [row[0] for row in result.all()]
            
            if not agents:
                return {
                    "total_agents": 0,
                    "total_trades": 0,
                    "total_premium": 0.0,
                    "total_pnl": 0.0,
                    "avg_win_rate": 0.0,
                }
            
            # Aggregate across all agents
            agent_metrics = []
            total_trades = 0
            total_premium = 0.0
            total_pnl = 0.0
            
            for agent in agents:
                metrics = await self.get_agent_metrics(agent)
                agent_metrics.append(metrics)
                total_trades += metrics["total_trades"]
                total_premium += metrics["total_premium_collected"]
                total_pnl += metrics["total_pnl"]
            
            avg_win_rate = (
                sum(m["win_rate"] for m in agent_metrics) / len(agent_metrics)
                if agent_metrics else 0.0
            )
            
            return {
                "total_agents": len(agents),
                "total_trades": total_trades,
                "total_premium": round(total_premium, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_win_rate": round(avg_win_rate, 2),
                "agents": agent_metrics,
            }
    
    async def get_trade_history(
        self,
        agent_name: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Trade]:
        """
        Get paginated trade history with filters.
        
        Args:
            agent_name: Filter by agent
            symbol: Filter by symbol
            start_date: Start date filter
            end_date: End date filter
            limit: Maximum number of results
            offset: Pagination offset
        
        Returns:
            List of Trade objects
        """
        async with AsyncSessionLocal() as session:
            conditions = []
            
            if agent_name:
                conditions.append(Trade.agent_name == agent_name)
            if symbol:
                conditions.append(Trade.symbol == symbol)
            if start_date:
                conditions.append(Trade.created_at >= start_date)
            if end_date:
                conditions.append(Trade.created_at <= end_date)
            
            stmt = select(Trade)
            if conditions:
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(desc(Trade.created_at)).limit(limit).offset(offset)
            
            result = await session.execute(stmt)
            return list(result.scalars().all())
