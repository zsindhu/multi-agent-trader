"""
Tier 2b LLM Reasoning Layer — Narrative reasoning over Tier 2a promotions.

Reads Tier 2a promoted names from name_observations, constructs per-name
context blocks from the mechanical signal data, sends batches to Llama 3.3
via Together AI, and stores the reasoning strings back into each
observation's analysis JSON.

Purpose: produce short natural-language reasoning for each promoted name
explaining WHY the signal combination is interesting. This becomes the
input the Lead Agent reads when making trade decisions.

Model: Llama 3.3 70B via Together AI (OpenAI-compatible API).
Cost: ~$3-6/month at current Tier 2a promotion volumes.
"""
import asyncio
import json
import math
import re
from datetime import datetime, timezone
from typing import Optional

import yaml
from loguru import logger
from sqlalchemy import select, update

from agents.base_agent import BaseAgent
from config.settings import settings
from core.database import AsyncSessionLocal
from models.name_observation import NameObservation
from models.agent_action import AgentAction


class Tier2bReasoning(BaseAgent):
    """Tier 2b: LLM narrative reasoning over Tier 2a mechanical promotions."""

    def __init__(self, config_path: str = "config/tier2b.yaml"):
        super().__init__(name="Tier2b-Reasoning", agent_type="analyst")
        self.config = self._load_config(config_path)
        self._client = None
        self._enabled = False
        self._init_client()

    def _init_client(self):
        """Initialize the Together AI client via OpenAI-compatible interface."""
        if not settings.together_api_key:
            logger.warning("[Tier2b] Tier 2b disabled — TOGETHER_API_KEY not configured")
            return

        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url="https://api.together.xyz/v1",
            )
            self._enabled = True
            logger.info(f"[Tier2b] Initialized with model {self.config.get('model', 'unknown')}")
        except Exception as e:
            logger.error(f"[Tier2b] Failed to initialize Together AI client: {e}")

    @staticmethod
    def _load_config(path: str) -> dict:
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
            return raw.get("tier2b_reasoning", {})
        except FileNotFoundError:
            logger.warning(f"[Tier2b] Config not found at {path}, using defaults")
            return {}
        except Exception as e:
            logger.error(f"[Tier2b] Failed to load config: {e}")
            return {}

    # ── BaseAgent lifecycle (not used) ───────────────────────────

    async def scan(self) -> list:
        return []

    async def evaluate(self, opportunities) -> list:
        return []

    async def execute(self, trades) -> list:
        return []

    async def manage_positions(self) -> list:
        return []

    # ── Main sweep ───────────────────────────────────────────────

    async def run_sweep(self, dry_run: bool = False) -> dict:
        """
        Run Tier 2b reasoning over current Tier 2a promotions.

        Reads promoted names, batches to LLM, stores reasoning strings
        back into analysis JSON.
        """
        if not self._enabled:
            logger.warning("[Tier2b] Skipping — not enabled (no TOGETHER_API_KEY)")
            return {"skipped": True, "reason": "not_enabled"}

        cfg = self.config
        batch_size = cfg.get("batch_size", 25)
        sleep_s = cfg.get("batch_sleep_seconds", 1.0)

        start_time = datetime.now(timezone.utc)
        cycle_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        await self._log_action("tier2b_sweep_started", "in_progress", None, {"dry_run": dry_run})
        logger.info(f"[Tier2b] Sweep starting (dry_run={dry_run})")

        # Step 1: Get current Tier 2a promoted names
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(NameObservation)
                    .where(NameObservation.tier == 2)
                    .where(NameObservation.was_considered == True)
                    .where(NameObservation.timestamp >= cycle_start)
                    .order_by(NameObservation.composite_score.desc())
                )
                promotions = list(result.scalars().all())
        except Exception as e:
            logger.error(f"[Tier2b] Failed to fetch Tier 2a promotions: {e}")
            await self._log_action("tier2b_sweep_failed", "failed", str(e), None)
            return {"error": str(e)}

        if not promotions:
            logger.info("[Tier2b] No Tier 2a promotions found for today")
            await self._log_action("tier2b_sweep_completed", "executed", "no_promotions", {"count": 0})
            return {"processed": 0, "reasoned": 0, "errors": 0}

        logger.info(f"[Tier2b] {len(promotions)} promoted names to process")

        # Step 2: Build context blocks
        context_blocks = []
        for obs in promotions:
            ctx = self._build_context(obs)
            context_blocks.append({"obs_id": obs.id, "symbol": obs.symbol, "context": ctx})

        # Step 3: Batch and call LLM
        reasoned = 0
        errors = 0
        total_batches = math.ceil(len(context_blocks) / batch_size)

        for batch_idx in range(0, len(context_blocks), batch_size):
            batch = context_blocks[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1

            try:
                reasoning_map = await self._get_reasoning_batch(batch)

                if not dry_run:
                    written = await self._update_observations(reasoning_map, cycle_start)
                    reasoned += written
                else:
                    for sym, reasoning in reasoning_map.items():
                        print(f"  {sym}: {reasoning[:120]}...")
                    reasoned += len(reasoning_map)

            except Exception as e:
                logger.warning(f"[Tier2b] Batch {batch_num}/{total_batches} failed: {e}")
                errors += 1
                # Store failure markers for names in this batch
                if not dry_run:
                    fail_map = {
                        item["symbol"]: f"reasoning_failed: batch error — {str(e)[:150]}"
                        for item in batch
                    }
                    await self._update_observations(fail_map, cycle_start)

            if batch_num % 5 == 0 or batch_num == total_batches:
                logger.info(f"[Tier2b] Batch {batch_num}/{total_batches}: {reasoned} reasoned, {errors} errors")

            if batch_idx + batch_size < len(context_blocks):
                await asyncio.sleep(sleep_s)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary = {
            "processed": len(promotions),
            "reasoned": reasoned,
            "errors": errors,
            "elapsed_seconds": round(elapsed, 1),
            "dry_run": dry_run,
        }
        await self._log_action("tier2b_sweep_completed", "executed", None, summary)
        logger.info(f"[Tier2b] Sweep complete: {summary}")
        return summary

    # ── Context building ─────────────────────────────────────────

    def _build_context(self, obs: NameObservation) -> str:
        """Build a compact context string for one promoted name."""
        analysis = obs.analysis or {}
        signals = analysis.get("signals", {})
        amp = analysis.get("amplification_applied", 1.0)

        # Firing signals
        firing = []
        for name, sig in signals.items():
            if sig.get("fired"):
                raw = sig.get("raw", "")
                firing.append(f"{name}(raw={raw})")

        # Earnings info
        ep = signals.get("earnings_proximity", {})
        earnings_str = ""
        if ep.get("fired"):
            earnings_str = f" | Earnings: {ep.get('raw')} days (amp={amp}x)"

        # News state
        news = signals.get("news_density", {})
        news_reason = news.get("reason", "unknown")
        news_str = f" | News: {news_reason}"
        if news.get("fired"):
            news_str = f" | News: density z={news.get('raw', 0)}"

        score = obs.composite_score or 0
        price = obs.price or 0
        asset_type = obs.asset_type or "stock"

        lines = [
            f"{obs.symbol} | ${price:.2f} | {asset_type} | score={score:.4f}",
            f"  Signals fired: {', '.join(firing) if firing else 'none'}",
        ]
        if earnings_str:
            lines.append(f"  {earnings_str.strip(' |')}")
        lines.append(f"  {news_str.strip(' |')}")

        return "\n".join(lines)

    # ── LLM calls ────────────────────────────────────────────────

    async def _get_reasoning_batch(self, batch: list[dict]) -> dict[str, str]:
        """
        Call Together AI for a batch of names.
        Returns dict mapping symbol -> reasoning string.
        """
        cfg = self.config
        model = cfg.get("model", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
        max_tokens = cfg.get("max_tokens_per_reasoning", 150) * len(batch)
        temperature = cfg.get("temperature", 0.3)
        system_prompt = cfg.get("system_prompt", "Analyze each name and respond with a JSON array of {symbol, reasoning} objects.")

        # Build the user message with all name contexts
        name_blocks = "\n\n".join(
            f"--- {item['symbol']} ---\n{item['context']}"
            for item in batch
        )
        user_message = f"Names to analyze ({len(batch)} total):\n\n{name_blocks}"

        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        raw_content = response.choices[0].message.content.strip()
        return self._parse_reasoning_response(raw_content, batch)

    def _parse_reasoning_response(self, raw_content: str, batch: list[dict]) -> dict[str, str]:
        """
        Parse LLM response into {symbol: reasoning} map.
        Three-level fallback: JSON parse → regex extraction → failure marker.
        """
        batch_symbols = {item["symbol"] for item in batch}
        result = {}

        # Level 1: Try clean JSON parse
        try:
            # Strip markdown code fences if present
            content = raw_content
            if "```" in content:
                content = re.sub(r"```(?:json)?\s*", "", content)
                content = content.replace("```", "")
            content = content.strip()

            parsed = json.loads(content)
            if isinstance(parsed, list):
                for entry in parsed:
                    if isinstance(entry, dict) and "symbol" in entry and "reasoning" in entry:
                        sym = entry["symbol"].upper()
                        if sym in batch_symbols:
                            result[sym] = str(entry["reasoning"])[:500]
                if result:
                    return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Level 2: Best-effort regex extraction
        logger.warning(f"[Tier2b] JSON parse failed, attempting regex extraction. Raw response (first 300 chars): {raw_content[:300]}")
        try:
            pattern = r'"symbol"\s*:\s*"([^"]+)"[^}]*"reasoning"\s*:\s*"([^"]*(?:\\.[^"]*)*)"'
            matches = re.findall(pattern, raw_content, re.DOTALL)
            for sym, reasoning in matches:
                sym_upper = sym.upper()
                if sym_upper in batch_symbols:
                    result[sym_upper] = reasoning.replace('\\"', '"')[:500]
            if result:
                logger.info(f"[Tier2b] Regex extracted {len(result)} of {len(batch)} reasoning strings")
                return result
        except Exception:
            pass

        # Level 3: Store failure marker for all names in batch
        logger.warning(f"[Tier2b] All parsing failed. Raw (first 200): {raw_content[:200]}")
        for item in batch:
            result[item["symbol"]] = f"reasoning_failed: {raw_content[:200]}"

        return result

    # ── Database updates ─────────────────────────────────────────

    async def _update_observations(self, reasoning_map: dict[str, str], cycle_start: datetime) -> int:
        """
        Update analysis JSON for Tier 2a observations to add tier2b_reasoning.
        Only touches rows from the current cycle (belt-and-suspenders).
        """
        if not reasoning_map:
            return 0

        written = 0
        try:
            async with AsyncSessionLocal() as session:
                for symbol, reasoning in reasoning_map.items():
                    result = await session.execute(
                        select(NameObservation)
                        .where(NameObservation.tier == 2)
                        .where(NameObservation.was_considered == True)
                        .where(NameObservation.symbol == symbol)
                        .where(NameObservation.timestamp >= cycle_start)
                        .limit(1)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        existing = row.analysis or {}
                        existing["tier2b_reasoning"] = reasoning
                        row.analysis = existing
                        written += 1

                await session.commit()
        except Exception as e:
            logger.error(f"[Tier2b] Failed to update observations: {e}")

        return written

    # ── Audit logging ────────────────────────────────────────────

    async def _log_action(self, action_type: str, outcome: str, reason: Optional[str], payload: Optional[dict]):
        """Write to agent_actions."""
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentAction(
                    agent_name=self.name,
                    action_type=action_type,
                    target_scope="universe",
                    outcome=outcome,
                    reason=reason,
                    payload=payload,
                ))
                await session.commit()
        except Exception as e:
            logger.warning(f"[Tier2b] Failed to log action {action_type}: {e}")
