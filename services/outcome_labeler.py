"""
Outcome Labeler — Joins completed trades to the signal profiles that
produced them, computes PnL, holding period, and underlying return.

Runs nightly at 5 PM ET. Idempotent — skips trades already labeled
(unique constraint on trade_id in trade_outcomes).

This is the ground truth substrate for:
- Statistical signal-weight learner (1.4.2.2)
- Research Analyst reflection (1.4.2.3)
- Citation tracking (1.4.2.5)
"""
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, func as sa_func

from core.database import AsyncSessionLocal
from models.trade import Trade
from models.trade_outcome import TradeOutcome
from models.name_observation import NameObservation
from models.historical_bar import HistoricalBar


# Funnel cutover date — trades after this date may have matching observations
FUNNEL_CUTOVER = date(2026, 4, 20)

# Completed trade statuses to process
COMPLETED_STATUSES = {"expired", "closed", "assigned"}


class OutcomeLabeler:
    """Labels completed trades with outcomes and joins to signal profiles."""

    async def run(self, dry_run: bool = False) -> dict:
        """
        Find newly-completed trades, compute outcomes, join to observations.
        Returns summary dict.
        """
        logger.info(f"[Labeler] Starting outcome labeling (dry_run={dry_run})")

        # Step 1: Find completed trades not yet labeled
        try:
            async with AsyncSessionLocal() as session:
                # Get trade_ids already labeled
                labeled_result = await session.execute(
                    select(TradeOutcome.trade_id)
                )
                labeled_ids = {r[0] for r in labeled_result.all()}

                # Get trades with completed statuses (existing logic)
                result = await session.execute(
                    select(Trade)
                    .where(Trade.status.in_(COMPLETED_STATUSES))
                    .order_by(Trade.created_at)
                )
                status_trades = list(result.scalars().all())

                # Get round-trip trades: sell_to_open with a matching
                # buy_to_close (status=filled). These are actively managed
                # positions closed before expiration.
                round_trip_trades = await self._find_round_trip_trades(session)

                # Merge, dedup by trade id
                seen_ids = {t.id for t in status_trades}
                all_trades = list(status_trades)
                for t in round_trip_trades:
                    if t.id not in seen_ids:
                        all_trades.append(t)
                        seen_ids.add(t.id)

        except Exception as e:
            logger.error(f"[Labeler] Failed to fetch trades: {e}")
            return {"error": str(e)}

        unlabeled = [t for t in all_trades if t.id not in labeled_ids]
        logger.info(f"[Labeler] {len(unlabeled)} unlabeled completed trades (of {len(all_trades)} total)")

        if not unlabeled:
            return {"labeled": 0, "skipped": 0, "errors": 0}

        # Step 2: Process each trade
        outcomes = []
        errors = 0

        for trade in unlabeled:
            try:
                outcome = await self._label_trade(trade)
                if outcome:
                    outcomes.append(outcome)
                    if dry_run:
                        self._print_outcome(trade, outcome)
            except Exception as e:
                logger.warning(f"[Labeler] Failed to label trade {trade.id} ({trade.symbol}): {e}")
                errors += 1

        # Step 3: Write outcomes
        if not dry_run and outcomes:
            try:
                async with AsyncSessionLocal() as session:
                    for outcome in outcomes:
                        session.add(outcome)
                    await session.commit()
                logger.info(f"[Labeler] Wrote {len(outcomes)} outcomes")
            except Exception as e:
                logger.error(f"[Labeler] Failed to write outcomes: {e}")
                errors += 1

        funnel_count = sum(1 for o in outcomes if o.funnel_driven)
        summary = {
            "labeled": len(outcomes),
            "from_funnel": funnel_count,
            "pre_funnel": len(outcomes) - funnel_count,
            "errors": errors,
            "dry_run": dry_run,
        }
        logger.info(f"[Labeler] Complete: {summary}")
        return summary

    async def _find_round_trip_trades(self, session) -> list:
        """
        Find sell_to_open trades that have a matching buy_to_close with
        status 'filled'. These are completed round-trips closed before
        expiration. Returns the sell_to_open trades (the entry decisions).
        """
        # All sell_to_open trades
        sto_result = await session.execute(
            select(Trade)
            .where(Trade.trade_type == "sell_to_open")
            .order_by(Trade.created_at)
        )
        sto_trades = list(sto_result.scalars().all())

        if not sto_trades:
            return []

        # All buy_to_close trades with status filled
        btc_result = await session.execute(
            select(Trade)
            .where(Trade.trade_type == "buy_to_close")
            .where(Trade.status == "filled")
            .order_by(Trade.created_at)
        )
        btc_trades = list(btc_result.scalars().all())

        # Index BTC trades by (symbol, strike, expiration) for matching
        btc_by_key = {}
        for btc in btc_trades:
            key = (btc.symbol, str(btc.strike), str(btc.expiration))
            btc_by_key.setdefault(key, []).append(btc)

        # Store round-trip mapping for use during labeling
        self._round_trip_map = {}  # sell_to_open.id -> buy_to_close Trade
        round_trip_entries = []

        for sto in sto_trades:
            key = (sto.symbol, str(sto.strike), str(sto.expiration))
            matches = btc_by_key.get(key, [])
            # Find the first BTC that happened after the STO
            for btc in matches:
                if btc.created_at and sto.created_at and btc.created_at >= sto.created_at:
                    self._round_trip_map[sto.id] = btc
                    round_trip_entries.append(sto)
                    break

        logger.info(f"[Labeler] Found {len(round_trip_entries)} round-trip trades (sell_to_open + buy_to_close)")
        return round_trip_entries

    async def _label_trade(self, trade: Trade) -> Optional[TradeOutcome]:
        """Compute outcome for a single trade."""

        # Check if this is a round-trip trade with a matching buy_to_close
        btc_trade = getattr(self, '_round_trip_map', {}).get(trade.id)

        # Compute PnL
        pnl_dollars = self._compute_pnl(trade, btc_trade=btc_trade)
        premium_at_risk = self._compute_premium_at_risk(trade)
        pnl_percent = (pnl_dollars / premium_at_risk * 100) if premium_at_risk and pnl_dollars is not None else None

        # Determine outcome
        if pnl_dollars is None:
            outcome = "pending"
        elif pnl_dollars > 0:
            outcome = "win"
        elif pnl_dollars < 0:
            outcome = "loss"
        else:
            outcome = "breakeven"

        # Holding period — use BTC close date for round-trips
        holding_days = self._compute_holding_days(trade, btc_trade=btc_trade)

        # Underlying return during holding period
        underlying_return = await self._compute_underlying_return(trade, btc_trade=btc_trade)

        # Join to name_observations (funnel-driven trades only)
        obs_id = None
        signal_profile = None
        trade_date = trade.created_at.date() if trade.created_at else None
        funnel_driven = trade_date is not None and trade_date >= FUNNEL_CUTOVER

        if funnel_driven and trade_date:
            obs_id, signal_profile = await self._find_observation(trade.symbol, trade_date)
            if obs_id is None:
                funnel_driven = False  # No matching observation found

        return TradeOutcome(
            trade_id=trade.id,
            name_observation_id=obs_id,
            funnel_driven=funnel_driven,
            outcome=outcome,
            pnl_dollars=round(pnl_dollars, 2) if pnl_dollars is not None else None,
            pnl_percent=round(pnl_percent, 2) if pnl_percent is not None else None,
            holding_days=holding_days,
            underlying_return=round(underlying_return, 4) if underlying_return is not None else None,
            signal_profile=signal_profile,
        )

    def _compute_pnl(self, trade: Trade, btc_trade: Optional[Trade] = None) -> Optional[float]:
        """Compute PnL for a completed trade."""
        # Round-trip trade: PnL from the buy_to_close record
        if btc_trade is not None:
            # If the BTC record has an explicit PnL, use it
            if btc_trade.pnl is not None:
                return float(btc_trade.pnl)
            # Otherwise compute: sold premium - bought premium (per contract * 100)
            sell_premium = float(trade.premium or trade.price or 0)
            buy_premium = float(btc_trade.premium or btc_trade.price or 0)
            qty = abs(trade.quantity or 1)
            return (sell_premium - buy_premium) * qty * 100

        # Use existing PnL if populated
        if trade.pnl is not None:
            return float(trade.pnl)

        premium = float(trade.premium or trade.price or 0)
        qty = abs(trade.quantity or 1)

        if trade.status == "expired":
            if trade.trade_type == "sell_to_open" or trade.side == "sell":
                # Sold option expired worthless — full premium capture
                return premium * qty * 100
            elif trade.trade_type == "buy_to_open" or trade.side == "buy":
                # Bought option expired worthless — total loss of premium paid
                return -(premium * qty * 100)

        if trade.status == "assigned":
            # CSP assigned — loss depends on strike vs current price
            # Can't compute precisely without current price, flag as negative
            return -(premium * qty * 100)  # Approximate: lost the premium cushion

        # Closed but no PnL — can't infer
        return None

    def _compute_premium_at_risk(self, trade: Trade) -> Optional[float]:
        """Compute the premium/collateral at risk for percentage calculation."""
        premium = float(trade.premium or trade.price or 0)
        qty = abs(trade.quantity or 1)
        strike = float(trade.strike or 0)

        if trade.side == "sell" or trade.trade_type == "sell_to_open":
            # CSP: collateral at risk = strike * 100 * qty
            if strike > 0:
                return strike * 100 * qty
            return premium * 100 * qty  # Fallback
        else:
            # Long option: premium paid is the risk
            return premium * 100 * qty if premium > 0 else None

    def _compute_holding_days(self, trade: Trade, btc_trade: Optional[Trade] = None) -> Optional[int]:
        """Compute days from entry to exit."""
        if not trade.created_at:
            return None

        # Round-trip: use buy_to_close created_at as exit date
        if btc_trade is not None and btc_trade.created_at:
            return (btc_trade.created_at.date() - trade.created_at.date()).days

        exit_date = trade.closed_at
        if exit_date is None and trade.expiration:
            try:
                exit_date = datetime.fromisoformat(trade.expiration)
            except (ValueError, TypeError):
                try:
                    exit_date = datetime.strptime(trade.expiration, "%Y-%m-%d")
                except (ValueError, TypeError):
                    return None

        if exit_date is None:
            return None

        return (exit_date.date() - trade.created_at.date()).days if hasattr(exit_date, 'date') else None

    async def _compute_underlying_return(self, trade: Trade, btc_trade: Optional[Trade] = None) -> Optional[float]:
        """Compute the underlying stock's return during the trade's holding period."""
        if not trade.created_at or not trade.symbol:
            return None

        entry_date = trade.created_at.date()

        exit_date = None
        # Round-trip: use buy_to_close date
        if btc_trade is not None and btc_trade.created_at:
            exit_date = btc_trade.created_at.date()
        elif trade.closed_at:
            exit_date = trade.closed_at.date()
        elif trade.expiration:
            try:
                exit_date = date.fromisoformat(trade.expiration)
            except (ValueError, TypeError):
                return None

        if exit_date is None or exit_date <= entry_date:
            return None

        try:
            async with AsyncSessionLocal() as session:
                # Get entry price (closest bar on or before entry date)
                r1 = await session.execute(
                    select(HistoricalBar.close)
                    .where(HistoricalBar.symbol == trade.symbol)
                    .where(HistoricalBar.bar_date <= entry_date)
                    .order_by(HistoricalBar.bar_date.desc())
                    .limit(1)
                )
                entry_close = r1.scalar()

                # Get exit price (closest bar on or before exit date)
                r2 = await session.execute(
                    select(HistoricalBar.close)
                    .where(HistoricalBar.symbol == trade.symbol)
                    .where(HistoricalBar.bar_date <= exit_date)
                    .order_by(HistoricalBar.bar_date.desc())
                    .limit(1)
                )
                exit_close = r2.scalar()

            if entry_close and exit_close and entry_close > 0:
                return (exit_close - entry_close) / entry_close

        except Exception as e:
            logger.debug(f"[Labeler] Underlying return failed for {trade.symbol}: {e}")

        return None

    async def _find_observation(self, symbol: str, trade_date: date) -> tuple:
        """Find the Tier 2 observation that led to this trade."""
        try:
            trade_datetime = datetime.combine(trade_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(NameObservation)
                    .where(NameObservation.symbol == symbol)
                    .where(NameObservation.tier == 2)
                    .where(NameObservation.was_considered == True)
                    .where(NameObservation.timestamp <= trade_datetime + timedelta(days=1))
                    .order_by(NameObservation.timestamp.desc())
                    .limit(1)
                )
                obs = result.scalar_one_or_none()

            if obs:
                return obs.id, obs.analysis
        except Exception as e:
            logger.debug(f"[Labeler] Observation lookup failed for {symbol}: {e}")

        return None, None

    def _print_outcome(self, trade: Trade, outcome: TradeOutcome):
        """Print a dry-run outcome for inspection."""
        print(
            f"  Trade #{trade.id} {trade.symbol} {trade.trade_type} "
            f"→ {outcome.outcome} | PnL=${outcome.pnl_dollars or 0:.2f} "
            f"({outcome.pnl_percent or 0:.1f}%) | {outcome.holding_days or '?'}d "
            f"| underlying={outcome.underlying_return or 0:.2%} "
            f"| funnel={outcome.funnel_driven}"
        )
