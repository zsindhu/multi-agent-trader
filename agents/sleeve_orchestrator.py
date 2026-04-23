"""
Sleeve Orchestrator — Runs 4 parallel Lead Agent calls (one per sleeve)
with per-sleeve system prompts and filtered Tier 2 lists, followed by a
consolidation call for cross-sleeve conflict resolution.

Architecture:
1. Global operations (reconcile, sync, position detection) run ONCE
2. Per-sleeve operations (LLM call with sleeve context) run 4x in sequence
3. Consolidation: deterministic conflict resolution + LLM fallback
4. Risk gate: SleeveRiskGate checks every action before execution
5. Actions dispatched through existing Lead Agent._execute_action()

The existing Lead Agent is the fallback — if no sleeve configs exist,
run_cycle() delegates to lead_agent.run_cycle() directly.
"""
import json
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select

from agents.lead_agent import LeadAgent
from core.database import AsyncSessionLocal
from models.name_observation import NameObservation
from models.agent_action import AgentAction
from services.sleeve_config import SleeveConfig, load_sleeve_configs
from services.sleeve_risk_gate import SleeveRiskGate


def _resolve_conflict_deterministic(symbol: str, competing_sleeves: list[dict], all_signals: dict) -> str:
    """
    Deterministic conflict resolution — ONLY for genuinely non-contested cases.

    Currently only ETFs are non-contested: no other sleeve's scanner filter
    promotes ETFs, so sector_rotation is the only valid claimant.

    All other conflicts route to LLM consolidation to preserve research
    integrity — the 6-month experiment needs sleeves competing on equal
    footing, not biased by a priority table that pre-assumes which sleeve
    "should" handle which setup type.

    Returns sleeve_id if resolved deterministically, or None if LLM needed.
    """
    signals = all_signals.get(symbol, {})
    asset_type = signals.get("_asset_type", "stock")
    sleeve_ids = [s["sleeve_id"] for s in competing_sleeves]

    # ETF → sector_rotation (genuinely non-contested)
    if "sector_rotation" in sleeve_ids and asset_type == "etf":
        return "sector_rotation"

    # Everything else → route to LLM consolidation
    return None


class SleeveOrchestrator:
    """Orchestrates parallel Lead Agent calls across strategy sleeves."""

    def __init__(self, lead_agent: LeadAgent, sleeve_configs: dict[str, SleeveConfig] = None):
        self.lead = lead_agent
        self.sleeve_configs = sleeve_configs or load_sleeve_configs()
        self.risk_gate = SleeveRiskGate(
            portfolio=lead_agent.portfolio,
            total_capital=sum(c.capital_allocation for c in self.sleeve_configs.values()),
        )

    async def run_cycle(self) -> dict:
        """
        Run one full multi-sleeve orchestration cycle.

        Falls back to single Lead Agent if no sleeve configs loaded.
        """
        if not self.sleeve_configs:
            logger.info("[Orchestrator] No sleeve configs — falling back to single Lead Agent")
            return await self.lead.run_cycle()

        logger.info(f"[Orchestrator] ═══ Multi-sleeve cycle starting ({len(self.sleeve_configs)} sleeves) ═══")
        start_time = datetime.now(timezone.utc)

        # Step 1: Global operations (run once, not per sleeve)
        await self._run_global_operations()

        # Step 1.5: Load existing positions into risk gate for portfolio-level limits.
        # Existing (pre-sleeve) positions don't consume sleeve position slots but DO
        # count toward cross-sleeve name prevention + sector concentration + total
        # capital deployed. As positions close naturally, the portfolio transitions
        # to fully sleeve-attributed over ~45-60 days.
        self.risk_gate._sleeve_positions = {}
        self.risk_gate._all_positions = {}
        if self.lead.portfolio:
            for opt in self.lead.portfolio.options:
                self.risk_gate._all_positions[opt.symbol] = "legacy"

        # Step 2: Load today's Tier 2 promotions (universal — filter per sleeve later)
        all_promotions = await self._load_all_promotions()
        logger.info(f"[Orchestrator] {len(all_promotions)} Tier 2 promotions loaded")

        # Step 3: Build signal lookup for conflict resolution
        all_signals = {}
        for p in all_promotions:
            analysis = p.get("_analysis", {})
            signals = analysis.get("signals", {})
            signals["_asset_type"] = p.get("asset_type", "stock")
            all_signals[p["symbol"]] = signals

        # Step 4: Per-sleeve LLM calls
        sleeve_decisions = {}
        total_cost = 0.0

        for sleeve_id, config in self.sleeve_configs.items():
            try:
                filtered = self._filter_promotions_for_sleeve(all_promotions, config)
                logger.info(f"[Orchestrator] Sleeve '{config.name}': {len(filtered)} candidates")

                if not filtered:
                    sleeve_decisions[sleeve_id] = {"actions": [], "summary": "No candidates for this sleeve"}
                    continue

                decision = await self._run_sleeve_cycle(sleeve_id, config, filtered)
                sleeve_decisions[sleeve_id] = decision
                total_cost += decision.get("cost_usd", 0)

                logger.info(
                    f"[Orchestrator] Sleeve '{config.name}': "
                    f"{len(decision.get('actions', []))} actions, "
                    f"${decision.get('cost_usd', 0):.4f}"
                )
            except Exception as e:
                logger.error(f"[Orchestrator] Sleeve '{config.name}' failed: {e}")
                sleeve_decisions[sleeve_id] = {"actions": [], "error": str(e)}

        # Step 5: Consolidation — resolve cross-sleeve conflicts
        all_actions = await self._consolidate(sleeve_decisions, all_signals)
        logger.info(f"[Orchestrator] Consolidation: {len(all_actions)} actions after conflict resolution")

        # Step 6: Risk gate + execution
        executed = 0
        rejected = 0
        for action_entry in all_actions:
            action = action_entry["action"]
            sleeve_id = action_entry["sleeve_id"]
            config = self.sleeve_configs[sleeve_id]

            gate_result = await self.risk_gate.check_trade(
                action, sleeve_id, config.capital_allocation, config.max_positions,
            )

            if gate_result["approved"]:
                try:
                    await self.lead._execute_action(action)
                    executed += 1
                except Exception as e:
                    logger.error(f"[Orchestrator] Action execution failed: {e}")
            else:
                rejected += 1
                logger.info(f"[Orchestrator] Risk gate rejected {action.get('symbol', '?')} for {sleeve_id}: {gate_result['reason']}")

        # Step 7: Store cycle reasoning
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary = {
            "sleeves": len(self.sleeve_configs),
            "total_actions": len(all_actions),
            "executed": executed,
            "risk_rejected": rejected,
            "total_cost": round(total_cost, 4),
            "elapsed_seconds": round(elapsed, 1),
            "per_sleeve": {
                sid: {
                    "actions": len(d.get("actions", [])),
                    "summary": d.get("summary", "")[:200],
                }
                for sid, d in sleeve_decisions.items()
            },
        }

        await self._log_action("sleeve_cycle_completed", "executed", None, summary)
        logger.info(f"[Orchestrator] ═══ Cycle complete: {executed} executed, {rejected} rejected, ${total_cost:.4f} ═══")

        # Write equity snapshot
        from main import _write_equity_snapshot
        await _write_equity_snapshot(self.lead.portfolio)

        return summary

    # ── Global operations ────────────────────────────────────────

    async def _run_global_operations(self):
        """Reconcile + sync + detect changes (once per cycle, not per sleeve)."""
        if self.lead.order_reconciler:
            try:
                await self.lead.order_reconciler.reconcile()
            except Exception as e:
                logger.warning(f"[Orchestrator] Reconciliation failed: {e}")

        if self.lead.portfolio and self.lead.broker:
            await self.lead.portfolio.sync_from_broker(self.lead.broker)

        if self.lead.order_reconciler and self.lead.portfolio:
            try:
                current_syms = {opt.option_symbol for opt in self.lead.portfolio.options}
                await self.lead.order_reconciler.detect_position_changes(current_syms)
            except Exception:
                pass

    # ── Tier 2 loading + filtering ───────────────────────────────

    async def _load_all_promotions(self) -> list[dict]:
        """Load all today's Tier 2 promoted observations."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(NameObservation)
                    .where(NameObservation.tier == 2)
                    .where(NameObservation.was_considered == True)
                    .where(NameObservation.timestamp >= today_start)
                    .order_by(NameObservation.composite_score.desc())
                )
                rows = list(result.scalars().all())

            promotions = []
            for obs in rows:
                analysis = obs.analysis or {}
                signals = analysis.get("signals", {})
                firing = [n for n, s in signals.items() if s.get("fired")]

                promotions.append({
                    "symbol": obs.symbol,
                    "composite_score": obs.composite_score,
                    "price": obs.price,
                    "asset_type": obs.asset_type,
                    "daily_dollar_volume": obs.daily_dollar_volume,
                    "signals_fired": analysis.get("signals_fired", 0),
                    "firing_rules": firing,
                    "amplification_applied": analysis.get("amplification_applied", 1.0),
                    "analyst_reasoning": analysis.get("tier2b_reasoning"),
                    "_analysis": analysis,  # Full analysis for conflict resolution
                })
            return promotions
        except Exception as e:
            logger.error(f"[Orchestrator] Failed to load promotions: {e}")
            return []

    def _filter_promotions_for_sleeve(self, promotions: list[dict], config: SleeveConfig) -> list[dict]:
        """Filter universal Tier 2 promotions by sleeve scanner criteria."""
        sf = config.scanner_filter
        filtered = []

        for p in promotions:
            analysis = p.get("_analysis", {})
            signals = analysis.get("signals", {})

            # Earnings filter
            ep = signals.get("earnings_proximity", {})
            earnings_days = ep.get("raw")

            if sf.get("require_earnings_within_days"):
                if earnings_days is None or earnings_days > sf["require_earnings_within_days"]:
                    continue

            if sf.get("exclude_earnings_within_days"):
                if earnings_days is not None and 1 <= earnings_days <= sf["exclude_earnings_within_days"]:
                    continue

            # IV rank filter
            if sf.get("min_iv_rank_delta"):
                iv_delta = signals.get("iv_rank_delta", {}).get("raw", 0)
                if abs(iv_delta or 0) < sf["min_iv_rank_delta"]:
                    continue

            if sf.get("min_iv_rank"):
                # Approximate IV rank from iv_rank_delta signal context
                iv_delta = abs(signals.get("iv_rank_delta", {}).get("raw", 0))
                if iv_delta < sf["min_iv_rank"] * 0.3:  # Rough proxy
                    continue

            # Asset type filter
            if sf.get("asset_type"):
                if p.get("asset_type") != sf["asset_type"]:
                    continue

            # Symbol list filter
            if sf.get("require_symbols"):
                if p["symbol"] not in sf["require_symbols"]:
                    continue

            # News density filter (inverted for vol_reversion — low news wanted)
            if sf.get("max_news_density"):
                news = signals.get("news_density", {})
                if news.get("fired") and news.get("raw", 0) > sf["max_news_density"]:
                    continue

            # Dollar volume filter (e.g., yield_farming requires mega-caps)
            if sf.get("min_daily_dollar_volume"):
                ddv = p.get("daily_dollar_volume") or 0
                if ddv < sf["min_daily_dollar_volume"]:
                    continue

            filtered.append(p)

        # Return top 15 per sleeve (approved in architecture)
        return filtered[:15]

    # ── Per-sleeve LLM call ──────────────────────────────────────

    async def _run_sleeve_cycle(self, sleeve_id: str, config: SleeveConfig, candidates: list[dict]) -> dict:
        """Run one sleeve's LLM decision cycle."""
        if not self.lead.llm_service or not self.lead.llm_service.is_enabled:
            return {"actions": [], "summary": "LLM not available", "cost_usd": 0}

        system_prompt = self._build_sleeve_prompt(config)
        portfolio_summary = {
            "equity": self.lead.portfolio.equity if self.lead.portfolio else 0,
            "cash": self.lead.portfolio.cash if self.lead.portfolio else 0,
            "buying_power": self.lead.portfolio.buying_power if self.lead.portfolio else 0,
            "sleeve": sleeve_id,
            "sleeve_capital": config.capital_allocation,
            "open_positions": len(self.lead.portfolio.options) if self.lead.portfolio else 0,
        }

        # Build a sleeve-specific tool executor that returns filtered promotions
        original_executor = self.lead._execute_tool

        async def sleeve_tool_executor(tool_name: str, tool_input: dict) -> dict:
            if tool_name == "get_scanner_top":
                # Return sleeve-filtered candidates instead of universal top 50
                return {
                    "opportunities": [
                        {k: v for k, v in c.items() if not k.startswith("_")}
                        for c in candidates
                    ],
                    "source": f"tier2_funnel_sleeve_{sleeve_id}",
                    "sleeve": sleeve_id,
                }
            return await original_executor(tool_name, tool_input)

        decision = await self.lead.llm_service.get_cycle_decision(
            tools=self.lead._build_tools(),
            tool_executor=sleeve_tool_executor,
            portfolio_summary=portfolio_summary,
            system_prompt=system_prompt,
        )

        # Tag actions with sleeve_id
        for action in decision.get("actions", []):
            action["sleeve_id"] = sleeve_id

        return decision

    def _build_sleeve_prompt(self, config: SleeveConfig) -> str:
        """Build a focused system prompt for one sleeve."""
        dte_min, dte_max = config.dte_range
        return f"""You are the {config.name} sleeve of Premium Trader, an automated options premium selling system.

## Your Sleeve's Edge
{config.description}

## Your Constraints
- Maximum {config.max_positions} concurrent positions for this sleeve
- Target delta: {config.delta_target}
- DTE range: {dte_min}-{dte_max} days
- Capital allocation: ${config.capital_allocation:,.0f}

## Decision Framework
1. Read today's pre-market briefing (get_briefing) and playbook (get_playbook)
2. Check the market regime (get_regime)
3. Review your open positions (get_open_positions)
4. Evaluate the candidates from your sleeve's scanner (get_scanner_top)
5. For promising names, check fundamentals (get_fundamentals) and earnings (get_earnings_upcoming)

## Position Management
- Take profit at 50% of max premium (or sleeve-specific target)
- Close positions that are ITM with < 5 DTE
- Close positions > 50% underwater after evaluating context

## Output
For each candidate, decide: open a new position, or pass. Include an estimated_edge (0.50-0.95) for each trade you propose — your confidence that this trade will be profitable. This estimate is captured for calibration but does NOT affect sizing.

End with a JSON action block:
```json
[
  {{"action": "open_csp", "symbol": "AAPL", "delta": {config.delta_target}, "dte_target": {(dte_min + dte_max) // 2}, "contracts": 1, "estimated_edge": 0.72, "reason": "..."}},
  {{"action": "no_action", "reason": "No compelling setups for this sleeve today"}}
]
```

Valid actions: "close", "hold", "roll", "open_csp", "open_cc", "open_wheel", "no_action"

Be specific. Explain your reasoning before the JSON block."""

    async def _resolve_conflict_via_llm(self, symbol: str, claims: list[dict], all_signals: dict) -> str:
        """
        LLM-judged conflict resolution for contested names.

        Used when two sleeves both promote the same underlying with real
        reasoning — the experiment needs this resolved by thesis-fit analysis,
        not a priority table that pre-assumes which sleeve should handle which
        setup type.
        """
        if not self.lead.llm_service or not self.lead.llm_service.is_enabled:
            return None  # Caller falls back to load-balance

        signals = all_signals.get(symbol, {})
        sleeve_descriptions = []
        for c in claims:
            sid = c["sleeve_id"]
            cfg = self.sleeve_configs.get(sid)
            reason = c["action"].get("reason", "no reason given")
            sleeve_descriptions.append(
                f"- **{cfg.name if cfg else sid}**: {reason}"
            )

        prompt = f"""Two strategy sleeves both want to trade {symbol}. Each has a different thesis.

{chr(10).join(sleeve_descriptions)}

Signal profile for {symbol}:
- Signals fired: {[n for n, s in signals.items() if s.get('fired') and not n.startswith('_')]}
- Asset type: {signals.get('_asset_type', 'unknown')}

Which sleeve's thesis better explains why this specific setup is an opportunity right now? Respond with ONLY the sleeve name, nothing else. Choose based on which edge source is the primary driver for this particular setup."""

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=self.lead.llm_service.client.api_key if hasattr(self.lead.llm_service, 'client') else "",
                base_url="https://api.together.xyz/v1",
            )
            response = await client.chat.completions.create(
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.1,
            )
            answer = response.choices[0].message.content.strip().lower()

            # Match the answer to a sleeve_id
            for c in claims:
                sid = c["sleeve_id"]
                cfg = self.sleeve_configs.get(sid)
                if sid in answer or (cfg and cfg.name.lower() in answer):
                    logger.info(f"[Orchestrator] LLM conflict resolution on {symbol}: {sid}")
                    return sid

            logger.warning(f"[Orchestrator] LLM conflict response didn't match sleeves: '{answer}'")
            return None

        except Exception as e:
            logger.warning(f"[Orchestrator] LLM conflict resolution failed for {symbol}: {e}")
            return None

    # ── Consolidation ────────────────────────────────────────────

    async def _consolidate(self, sleeve_decisions: dict, all_signals: dict) -> list[dict]:
        """
        Merge actions from all sleeves. Resolve conflicts when multiple
        sleeves want the same symbol.

        Returns list of {action: dict, sleeve_id: str} for execution.
        """
        # Collect all proposed actions with sleeve tags
        all_proposed = []
        for sleeve_id, decision in sleeve_decisions.items():
            for action in decision.get("actions", []):
                if action.get("action") in ("no_action", "hold"):
                    continue
                action.setdefault("sleeve_id", sleeve_id)
                all_proposed.append({"action": action, "sleeve_id": sleeve_id})

        # Detect conflicts: multiple sleeves wanting the same symbol
        symbol_claims = {}
        for entry in all_proposed:
            symbol = entry["action"].get("symbol", "")
            if not symbol:
                continue
            if symbol not in symbol_claims:
                symbol_claims[symbol] = []
            symbol_claims[symbol].append(entry)

        # Resolve conflicts
        resolved = []
        for symbol, claims in symbol_claims.items():
            if len(claims) == 1:
                resolved.append(claims[0])
            else:
                # Multiple sleeves want this symbol
                sleeve_infos = [
                    {
                        "sleeve_id": c["sleeve_id"],
                        "position_count": len(self.risk_gate._sleeve_positions.get(c["sleeve_id"], [])),
                    }
                    for c in claims
                ]

                # Try deterministic resolution first (ETF-only)
                winner = _resolve_conflict_deterministic(symbol, sleeve_infos, all_signals)

                if winner is None:
                    # Contested — use LLM consolidation for research integrity
                    winner = await self._resolve_conflict_via_llm(symbol, claims, all_signals)

                if winner is None:
                    # LLM failed or unavailable — load-balance tiebreaker
                    min_pos = min(sleeve_infos, key=lambda s: s.get("position_count", 0))
                    winner = min_pos["sleeve_id"]
                    logger.info(f"[Orchestrator] Conflict on {symbol}: load-balance → {winner}")

                for c in claims:
                    if c["sleeve_id"] == winner:
                        resolved.append(c)
                        losers = [s["sleeve_id"] for s in sleeve_infos if s["sleeve_id"] != winner]
                        logger.info(f"[Orchestrator] Conflict on {symbol}: {winner} wins over {losers}")
                        break

        # Include close/roll/hold actions (they don't conflict)
        for entry in all_proposed:
            action_type = entry["action"].get("action", "")
            if action_type in ("close", "roll"):
                if entry not in resolved:
                    resolved.append(entry)

        return resolved

    # ── Logging ──────────────────────────────────────────────────

    async def _log_action(self, action_type: str, outcome: str, reason: Optional[str], payload: Optional[dict]):
        """Write to agent_actions."""
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentAction(
                    agent_name="Sleeve-Orchestrator",
                    action_type=action_type,
                    target_scope="portfolio",
                    outcome=outcome,
                    reason=reason,
                    payload=payload,
                ))
                await session.commit()
        except Exception as e:
            logger.warning(f"[Orchestrator] Failed to log action: {e}")
