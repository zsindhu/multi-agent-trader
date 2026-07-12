"""
Config Backtester — Replays historical Tier 2a observations under two
configs (current vs candidate) and compares promotion decisions.

Usage:
  python scripts/run_backtest_config.py config/tier2a.yaml config/tier2a_candidate.yaml
  python scripts/run_backtest_config.py config/tier2a.yaml config/tier2a_candidate.yaml --days 7
  python scripts/run_backtest_config.py config/tier2a.yaml config/tier2a_candidate.yaml --save

The backtester does NOT re-run signal computation. It reads the preserved
raw signal scores from analysis.signals in name_observations and applies
different weights + gate thresholds. This makes it fast (seconds, not minutes).

If --save is specified, records the comparison as a PendingChange entry.
"""
import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from loguru import logger
from sqlalchemy import select, func as sa_func

from core.database import AsyncSessionLocal
from models.name_observation import NameObservation
from models.trade_outcome import TradeOutcome
from models.pending_change import PendingChange


SIGNAL_NAMES = [
    "volume_zscore", "range_expansion", "gap_zscore", "iv_rank_delta",
    "correlation_breakdown", "earnings_proximity", "news_density",
    "put_call_ratio", "volume_oi_ratio", "short_interest", "social_velocity",
]


def load_config(path: str) -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return raw.get("tier2a_prefilter", raw)


def score_observation(analysis: dict, rules_cfg: dict, min_signals: int) -> dict:
    """Re-score an observation using the given config weights."""
    signals = analysis.get("signals", {})
    total_score = 0.0
    signals_fired = 0

    for name in SIGNAL_NAMES:
        sig = signals.get(name, {})
        rule_cfg = rules_cfg.get(name, {})
        if not rule_cfg.get("enabled", True):
            continue
        score = sig.get("score", 0.0)
        weight = rule_cfg.get("weight", 0.10)
        total_score += score * weight
        if sig.get("fired", False):
            signals_fired += 1

    # Earnings amplification
    ep_cfg = rules_cfg.get("earnings_proximity", {})
    ep = signals.get("earnings_proximity", {})
    if ep.get("fired", False):
        amp = ep_cfg.get("amplification_multiplier", 1.5)
        total_score *= amp

    promoted = signals_fired >= min_signals
    return {"score": total_score, "fired": signals_fired, "promoted": promoted}


async def run_backtest(current_path: str, candidate_path: str, days: int, save: bool):
    current_cfg = load_config(current_path)
    candidate_cfg = load_config(candidate_path)

    current_rules = current_cfg.get("rules", {})
    candidate_rules = candidate_cfg.get("rules", {})
    current_min = current_cfg.get("min_signals_to_fire", 2)
    candidate_min = candidate_cfg.get("min_signals_to_fire", 2)

    # Load historical tier=2 observations
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        from services.sweep_utils import sweep_dedup_filter
        result = await session.execute(
            select(NameObservation)
            .where(NameObservation.tier == 2)
            .where(NameObservation.timestamp >= cutoff)
            .where(sweep_dedup_filter(2, cutoff))
        )
        observations = list(result.scalars().all())

    if not observations:
        print(f"No tier=2 observations in the last {days} days. Nothing to backtest.")
        return

    print(f"Backtesting {len(observations)} observations over {days} days\n")

    # Load trade outcomes for win rate comparison
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TradeOutcome)
            .where(TradeOutcome.funnel_driven == True)
            .where(TradeOutcome.outcome.in_(["win", "loss"]))
        )
        outcomes = {o.name_observation_id: o.outcome for o in result.scalars().all()}

    # Score under both configs
    current_promoted = []
    candidate_promoted = []
    both_promoted = []
    only_current = []
    only_candidate = []

    for obs in observations:
        analysis = obs.analysis or {}
        c_result = score_observation(analysis, current_rules, current_min)
        p_result = score_observation(analysis, candidate_rules, candidate_min)

        entry = {
            "symbol": obs.symbol,
            "date": obs.timestamp.date().isoformat() if obs.timestamp else "?",
            "current_score": round(c_result["score"], 4),
            "candidate_score": round(p_result["score"], 4),
            "outcome": outcomes.get(obs.id),
        }

        if c_result["promoted"]:
            current_promoted.append(entry)
        if p_result["promoted"]:
            candidate_promoted.append(entry)
        if c_result["promoted"] and p_result["promoted"]:
            both_promoted.append(entry)
        elif c_result["promoted"] and not p_result["promoted"]:
            only_current.append(entry)
        elif not c_result["promoted"] and p_result["promoted"]:
            only_candidate.append(entry)

    # Compute win rates where outcome data exists
    def win_rate(entries):
        with_outcome = [e for e in entries if e["outcome"] in ("win", "loss")]
        if not with_outcome:
            return None, 0
        wins = sum(1 for e in with_outcome if e["outcome"] == "win")
        return round(wins / len(with_outcome) * 100, 1), len(with_outcome)

    current_wr, current_n = win_rate(current_promoted)
    candidate_wr, candidate_n = win_rate(candidate_promoted)

    # Print comparison
    print("=" * 60)
    print("CONFIG BACKTEST COMPARISON")
    print("=" * 60)
    print(f"  Period: last {days} days ({len(observations)} observations)")
    print(f"  Current config:   {len(current_promoted)} promoted", end="")
    if current_wr is not None:
        print(f" | win rate: {current_wr}% (n={current_n})")
    else:
        print(" | no outcome data")
    print(f"  Candidate config: {len(candidate_promoted)} promoted", end="")
    if candidate_wr is not None:
        print(f" | win rate: {candidate_wr}% (n={candidate_n})")
    else:
        print(" | no outcome data")
    print(f"\n  Both promote:     {len(both_promoted)}")
    print(f"  Only current:     {len(only_current)}")
    print(f"  Only candidate:   {len(only_candidate)}")

    # Weight diff
    print(f"\n  Weight changes:")
    for name in SIGNAL_NAMES:
        cw = current_rules.get(name, {}).get("weight", 0)
        pw = candidate_rules.get(name, {}).get("weight", 0)
        if cw != pw:
            print(f"    {name:25s} {cw:.3f} → {pw:.3f} ({((pw-cw)/cw*100) if cw else 0:+.0f}%)")

    if current_min != candidate_min:
        print(f"    min_signals_to_fire: {current_min} → {candidate_min}")

    print("=" * 60)

    # Show top divergences
    if only_candidate:
        print(f"\nTop 10 NEW promotions under candidate (not in current):")
        for e in sorted(only_candidate, key=lambda x: x["candidate_score"], reverse=True)[:10]:
            outcome_str = f" [{e['outcome']}]" if e["outcome"] else ""
            print(f"  {e['symbol']:6s} score={e['candidate_score']:.4f} date={e['date']}{outcome_str}")

    if only_current:
        print(f"\nTop 10 LOST promotions under candidate (in current, not candidate):")
        for e in sorted(only_current, key=lambda x: x["current_score"], reverse=True)[:10]:
            outcome_str = f" [{e['outcome']}]" if e["outcome"] else ""
            print(f"  {e['symbol']:6s} score={e['current_score']:.4f} date={e['date']}{outcome_str}")

    # Save as pending change if requested
    if save:
        backtest_result = {
            "days": days,
            "observations": len(observations),
            "current_promoted": len(current_promoted),
            "candidate_promoted": len(candidate_promoted),
            "current_win_rate": current_wr,
            "candidate_win_rate": candidate_wr,
            "only_candidate_count": len(only_candidate),
            "only_current_count": len(only_current),
        }
        try:
            async with AsyncSessionLocal() as session:
                session.add(PendingChange(
                    change_type="weight_update",
                    description=f"Backtest over {days} days: {len(candidate_promoted)} vs {len(current_promoted)} promotions",
                    proposed_config=candidate_cfg,
                    current_config=current_cfg,
                    backtest_result=backtest_result,
                    status="backtested",
                ))
                await session.commit()
            print(f"\nSaved as pending change (status=backtested)")
        except Exception as e:
            print(f"\nFailed to save pending change: {e}")


def main():
    parser = argparse.ArgumentParser(description="Config Backtester")
    parser.add_argument("current", help="Path to current tier2a config")
    parser.add_argument("candidate", help="Path to candidate tier2a config")
    parser.add_argument("--days", type=int, default=14, help="Days of history to backtest (default 14)")
    parser.add_argument("--save", action="store_true", help="Save result as pending change")
    args = parser.parse_args()

    asyncio.run(run_backtest(args.current, args.candidate, args.days, args.save))


if __name__ == "__main__":
    main()
