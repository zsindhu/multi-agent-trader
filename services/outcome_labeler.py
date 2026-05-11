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
from sqlalchemy import select, and_, func as sa_func
from sqlalchemy.orm import aliased

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
                    # Refresh to get IDs for embedding
                    for outcome in outcomes:
                        await session.refresh(outcome)
                logger.info(f"[Labeler] Wrote {len(outcomes)} outcomes")

                # Embed outcomes for semantic retrieval
                await self._embed_outcomes(outcomes, unlabeled)
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
        Find sell_to_open trades (status='filled') that have a matching
        buy_to_close (status='filled') on (symbol, strike, expiration)
        and don't already have a trade_outcomes row.

        Returns the sell_to_open trades (the entry decisions) and populates
        self._round_trip_map so _label_trade can find the matching BTC.
        """
        BTC = aliased(Trade)

        # SQL JOIN: STO joined to BTC on (symbol, strike, expiration),
        # LEFT JOIN trade_outcomes to exclude already-labeled
        sto_result = await session.execute(
            select(Trade)
            .join(
                BTC,
                and_(
                    Trade.symbol == BTC.symbol,
                    Trade.strike == BTC.strike,
                    Trade.expiration == BTC.expiration,
                    BTC.trade_type == "buy_to_close",
                    BTC.status == "filled",
                ),
            )
            .outerjoin(TradeOutcome, Trade.id == TradeOutcome.trade_id)
            .where(Trade.trade_type == "sell_to_open")
            .where(Trade.status == "filled")
            .where(TradeOutcome.id.is_(None))
            .order_by(Trade.created_at)
        )
        sto_trades = list(sto_result.scalars().unique().all())

        if not sto_trades:
            self._round_trip_map = {}
            logger.info("[Labeler] Found 0 round-trip trades (sell_to_open + buy_to_close)")
            return []

        # Fetch matching BTC trades to populate the round-trip map
        btc_result = await session.execute(
            select(Trade)
            .where(Trade.trade_type == "buy_to_close")
            .where(Trade.status == "filled")
            .order_by(Trade.created_at)
        )
        btc_trades = list(btc_result.scalars().all())

        # Index BTC by (symbol, strike, expiration)
        btc_by_key: dict[tuple, list[Trade]] = {}
        for btc in btc_trades:
            key = (btc.symbol, btc.strike, btc.expiration)
            btc_by_key.setdefault(key, []).append(btc)

        self._round_trip_map = {}
        for sto in sto_trades:
            key = (sto.symbol, sto.strike, sto.expiration)
            for btc in btc_by_key.get(key, []):
                if btc.created_at and sto.created_at and btc.created_at >= sto.created_at:
                    self._round_trip_map[sto.id] = btc
                    break

        logger.info(f"[Labeler] Found {len(sto_trades)} round-trip trades (sell_to_open + buy_to_close)")
        return sto_trades

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

    async def _embed_outcomes(self, outcomes: list, trades: list):
        """Embed trade outcomes for semantic retrieval."""
        try:
            from services.embeddings import EmbeddingsService
            emb = EmbeddingsService()
            if not emb.is_enabled:
                return
            # Build trade lookup for symbol context
            trade_by_id = {t.id: t for t in trades}
            for outcome in outcomes:
                trade = trade_by_id.get(outcome.trade_id)
                symbol = trade.symbol if trade else "unknown"
                text = (
                    f"Trade outcome: {symbol} {outcome.outcome} "
                    f"PnL=${outcome.pnl_dollars or 0:.2f} ({outcome.pnl_percent or 0:.1f}%) "
                    f"held {outcome.holding_days or '?'} days "
                    f"funnel_driven={outcome.funnel_driven}"
                )
                await emb.embed_and_store(
                    text=text,
                    source_table="trade_outcomes",
                    source_id=outcome.id,
                )
        except Exception as e:
            logger.debug(f"[Labeler] Outcome embedding failed: {e}")

    def _print_outcome(self, trade: Trade, outcome: TradeOutcome):
        """Print a dry-run outcome for inspection."""
        print(
            f"  Trade #{trade.id} {trade.symbol} {trade.trade_type} "
            f"→ {outcome.outcome} | PnL=${outcome.pnl_dollars or 0:.2f} "
            f"({outcome.pnl_percent or 0:.1f}%) | {outcome.holding_days or '?'}d "
            f"| underlying={outcome.underlying_return or 0:.2%} "
            f"| funnel={outcome.funnel_driven}"
        )
