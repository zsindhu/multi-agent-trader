"""
LLM Service — Lead Agent reasoning engine on an OpenAI-compatible endpoint.

Migrated July 2026 from the Anthropic SDK (claude-sonnet-4-6) to GLM-5.2 on
Together AI. The rest of the agent fleet (Tier 2b, research, summarizers,
chat) already speaks the OpenAI protocol on Together, so the lead agent now
uses the same transport. Tool definitions are still written in Anthropic
format ({name, description, input_schema}) in lead_agent.py and translated
here, which kept the migration surface to this one file.

Rollback/provider swap is config-only: set LLM_BASE_URL / LLM_MODEL in .env
to any OpenAI-compatible endpoint (Together, Z.ai, or Anthropic's
compatibility layer).

When TOGETHER_API_KEY is not set, is_enabled returns False and every call
returns an empty-actions dict — the Lead Agent falls back to rule-based logic.
"""
import asyncio
import json
import re
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from config.settings import settings

# zai-org/GLM-5.2 on Together AI (per-million-token, July 2026)
PRICE_INPUT = 1.40
PRICE_OUTPUT = 4.40
PRICE_CACHED_INPUT = 0.26


# ── Structured judgment envelope ─────────────────────────────────────
#
# Every LLM judgment should be queryable, not just a wall of prose. The
# envelope rides in the same fenced ```json block agents already emit for
# actions, and is stored alongside (never instead of) the full text. Parse
# failures degrade gracefully: full_text is always preserved and `degraded`
# marks the envelope as prose-only.

class JudgmentFactor(BaseModel):
    signal: str
    direction: str = "neutral"  # e.g. bullish / bearish / for / against
    weight: Optional[float] = None


class JudgmentEnvelope(BaseModel):
    verdict: Optional[str] = None
    one_liner: Optional[str] = None
    factors: list[JudgmentFactor] = Field(default_factory=list)
    confidence: Optional[float] = None
    full_text: str = ""
    schema_version: int = 1
    degraded: bool = False


def parse_envelope(text: str, envelope_obj: Optional[dict] = None) -> dict:
    """
    Build a JudgmentEnvelope dict from an LLM response.

    `envelope_obj` short-circuits parsing when the caller already extracted
    the envelope JSON (e.g. from the shared actions block). Otherwise the
    LAST fenced ```json block containing an object with an "envelope" key or
    envelope-shaped fields (verdict/one_liner) is used. On any failure the
    envelope degrades to full_text-only — data is never lost to a bad parse.

    Module-level so agents with their own LLM clients (tier2b, research
    analyst, summarizers) can adopt it without instantiating LLMService.
    """
    candidate = envelope_obj
    if candidate is None:
        for block in reversed(re.findall(r"```json\s*(.*?)\s*```", text or "", re.DOTALL)):
            try:
                parsed = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                if isinstance(parsed.get("envelope"), dict):
                    candidate = parsed["envelope"]
                    break
                if "verdict" in parsed or "one_liner" in parsed:
                    candidate = parsed
                    break

    if candidate is not None:
        try:
            env = JudgmentEnvelope(**{**candidate, "full_text": text or ""})
            return env.model_dump()
        except (ValidationError, TypeError) as e:
            logger.debug(f"[LLM] Envelope validation failed, degrading: {e}")

    return JudgmentEnvelope(full_text=text or "", degraded=True).model_dump()


class LLMService:
    """
    Wraps an OpenAI-compatible chat-completions API for Lead Agent
    decision-making.

    Accepts tools in Anthropic format (translated internally), sends them to
    the model, executes tool calls via the provided executor, and returns a
    structured decision dict.
    """

    MAX_DAILY_COST = 15.00  # Hard cap: $15/day (~$225/month safety net)

    def __init__(self):
        self._enabled = bool(settings.together_api_key)
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        if self._enabled:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url=settings.llm_base_url,
            )
            logger.info(
                f"[LLM] Initialized with model {self.model} @ {settings.llm_base_url}"
            )
        else:
            self.client = None
            logger.warning(
                "[LLM] No TOGETHER_API_KEY configured — "
                "Lead Agent will fall back to rule-based decisions"
            )
        # Daily usage tracking (resets at UTC midnight)
        self._daily_input_tokens: int = 0
        self._daily_output_tokens: int = 0
        self._daily_cost: float = 0.0
        self._cost_reset_date: date = datetime.utcnow().date()
        # The in-memory counter dies on restart; reload today's spend from
        # llm_usage_log on first use so the daily cap survives redeploys.
        self._daily_cost_loaded: bool = False
        # Caller tag for per-sleeve/per-agent cost attribution
        self._current_caller: str = "lead_agent"

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        """Translate Anthropic tool defs to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
            # Strip any cache_control leftovers defensively
            if t.get("name")
        ]

    async def get_cycle_decision(
        self,
        tools: list[dict],
        tool_executor,
        portfolio_summary: dict,
        system_prompt: str,
    ) -> dict:
        """
        Run a full Lead Agent reasoning cycle.

        Args:
            tools: Tool definitions in Anthropic format (translated here).
            tool_executor: async callable(tool_name, tool_input) → dict
            portfolio_summary: Current portfolio state (always included in context).
            system_prompt: The Lead Agent's identity and constraints.

        Returns:
            {
                "reasoning": str,      # the model's full reasoning text
                "actions": list[dict], # specific instructions for workers
                "summary": str,        # one-line summary for the dashboard
            }
        """
        if not self._enabled:
            return {
                "reasoning": "LLM not configured — using rule-based fallback",
                "actions": [],
                "summary": "Rule-based mode (no TOGETHER_API_KEY)",
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "model": self.model,
            }

        # Daily spending cap
        await self._load_persisted_daily_cost()
        self._reset_daily_if_needed()
        if self._daily_cost >= self.MAX_DAILY_COST:
            logger.warning(
                f"[LLM] Daily cost cap ${self.MAX_DAILY_COST:.2f} reached "
                f"(${self._daily_cost:.3f} spent today). Falling back to rules."
            )
            return {
                "reasoning": f"Daily LLM cost limit (${self.MAX_DAILY_COST:.2f}) reached — rule-based mode for rest of day.",
                "actions": [],
                "summary": f"Cost limit reached (${self._daily_cost:.3f} / ${self.MAX_DAILY_COST:.2f})",
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "model": self.model,
            }

        try:
            now_et = datetime.now(timezone(timedelta(hours=-4)))
            user_message = (
                f"It is {now_et.strftime('%A %B %d, %Y at %I:%M %p ET')}. "
                f"Markets are {'open' if self._is_market_hours() else 'closed'}.\n\n"
                f"Current portfolio state:\n"
                f"{json.dumps(portfolio_summary, indent=2, default=str)}\n\n"
                f"Analyze the current situation using your tools and decide "
                f"what actions to take this cycle. Be specific."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            openai_tools = self._to_openai_tools(tools)
            total_input_tokens = 0
            total_output_tokens = 0
            cost_before_cycle = self._daily_cost

            # Multi-turn tool use loop
            max_turns = 10
            for turn in range(max_turns):
                response = await self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=messages,
                    tools=openai_tools,
                )

                usage = response.usage
                cached = 0
                details = getattr(usage, "prompt_tokens_details", None)
                if details is not None:
                    cached = getattr(details, "cached_tokens", 0) or 0
                self._track_usage(usage.prompt_tokens, usage.completion_tokens, cached)
                total_input_tokens += usage.prompt_tokens
                total_output_tokens += usage.completion_tokens

                msg = response.choices[0].message

                if msg.tool_calls:
                    # Echo the assistant turn (with tool calls) back verbatim
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    })

                    for tc in msg.tool_calls:
                        tool_name = tc.function.name
                        try:
                            tool_input = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError as e:
                            logger.error(f"[LLM] Bad tool arguments for {tool_name}: {e}")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps({"error": f"invalid arguments: {e}"}),
                            })
                            continue

                        logger.info(
                            f"[LLM] Tool call: {tool_name}"
                            f"({json.dumps(tool_input)[:120]})"
                        )
                        try:
                            result = await tool_executor(tool_name, tool_input)
                            content = json.dumps(result, default=str)
                        except Exception as e:
                            logger.error(f"[LLM] Tool '{tool_name}' failed: {e}")
                            content = json.dumps({"error": str(e)})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": content,
                        })

                else:
                    # Model is done reasoning — extract the final text
                    final_text = msg.content or ""
                    cycle_cost = self._daily_cost - cost_before_cycle
                    logger.info(
                        f"[LLM] Cycle complete — "
                        f"{total_input_tokens} in / {total_output_tokens} out tokens "
                        f"| Cycle cost: ${cycle_cost:.4f} "
                        f"| Daily: ${self._daily_cost:.4f}"
                    )
                    decision = self._parse_decision(final_text)
                    decision["tokens_in"] = total_input_tokens
                    decision["tokens_out"] = total_output_tokens
                    decision["cost_usd"] = cycle_cost
                    decision["model"] = self.model
                    return decision

            logger.warning("[LLM] Hit max tool-use turns — no actions taken")
            cycle_cost = self._daily_cost - cost_before_cycle
            return {
                "reasoning": "Hit maximum reasoning turns without a final decision.",
                "actions": [],
                "summary": "Reasoning incomplete — no actions taken this cycle",
                "tokens_in": total_input_tokens, "tokens_out": total_output_tokens,
                "cost_usd": cycle_cost, "model": self.model,
            }

        except Exception as e:
            logger.error(f"[LLM] API error: {e}")
            return {
                "reasoning": f"LLM API error: {e}",
                "actions": [],
                "summary": "LLM API error — safe mode fallback active",
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "model": self.model,
            }

    async def _load_persisted_daily_cost(self) -> None:
        """One-time reload of today's spend from llm_usage_log after restart."""
        if self._daily_cost_loaded:
            return
        self._daily_cost_loaded = True
        try:
            from sqlalchemy import select, func as sa_func
            from core.database import AsyncSessionLocal
            from models.llm_usage_log import LlmUsageLog
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            async with AsyncSessionLocal() as session:
                r = await session.execute(
                    select(sa_func.sum(LlmUsageLog.cost_usd))
                    .where(LlmUsageLog.timestamp >= today_start)
                )
                persisted = float(r.scalar() or 0.0)
            if persisted > self._daily_cost:
                logger.info(f"[LLM] Restored today's spend from DB: ${persisted:.4f}")
                self._daily_cost = persisted
        except Exception as e:
            logger.debug(f"[LLM] Could not restore persisted daily cost: {e}")

    def _reset_daily_if_needed(self) -> None:
        today = datetime.utcnow().date()
        if today != self._cost_reset_date:
            self._daily_input_tokens = 0
            self._daily_output_tokens = 0
            self._daily_cost = 0.0
            self._cost_reset_date = today

    def _track_usage(self, input_tokens: int, output_tokens: int, cached_input: int = 0) -> None:
        self._reset_daily_if_needed()
        self._daily_input_tokens += input_tokens
        self._daily_output_tokens += output_tokens
        non_cached = max(input_tokens - cached_input, 0)
        call_cost = (
            (non_cached / 1_000_000) * PRICE_INPUT
            + (cached_input / 1_000_000) * PRICE_CACHED_INPUT
            + (output_tokens / 1_000_000) * PRICE_OUTPUT
        )
        self._daily_cost += call_cost
        if cached_input > 0:
            logger.info(
                f"[LLM] Cache: {cached_input:,} cached, {non_cached:,} uncached | "
                f"Savings: ${((cached_input / 1_000_000) * (PRICE_INPUT - PRICE_CACHED_INPUT)):.4f}"
            )

        # Persist to llm_usage_log (fire-and-forget)
        try:
            asyncio.get_event_loop().create_task(
                self._persist_usage(input_tokens, output_tokens, cached_input, call_cost)
            )
        except RuntimeError:
            pass  # No event loop — skip persistence (e.g. sync test context)

    async def _persist_usage(self, tokens_in: int, tokens_out: int, cache_read: int, cost: float) -> None:
        """Fire-and-forget write to llm_usage_log table."""
        try:
            from core.database import AsyncSessionLocal
            from models.llm_usage_log import LlmUsageLog
            async with AsyncSessionLocal() as session:
                session.add(LlmUsageLog(
                    model=self.model,
                    caller=self._current_caller,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cache_read=cache_read,
                    cache_create=0,
                    cost_usd=round(cost, 6),
                ))
                await session.commit()
        except Exception as e:
            logger.debug(f"[LLM] Usage log write failed (non-critical): {e}")

    def get_usage_stats(self) -> dict:
        self._reset_daily_if_needed()
        return {
            "enabled": self._enabled,
            "daily_input_tokens": self._daily_input_tokens,
            "daily_output_tokens": self._daily_output_tokens,
            "daily_cost_usd": round(self._daily_cost, 4),
            "daily_cost_limit_usd": self.MAX_DAILY_COST,
            "reset_date": self._cost_reset_date.isoformat(),
        }

    def _parse_decision(self, text: str) -> dict:
        """
        Parse the model's final response into a structured decision.

        Looks for a ```json block containing a list of action dicts or an
        object with "actions" (and optionally "envelope"). Falls back to
        empty actions if no valid JSON block is found.
        """
        actions = []
        envelope_obj = None

        json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        for block in json_blocks:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, list):
                    actions = parsed
                    break
                if isinstance(parsed, dict) and "actions" in parsed:
                    actions = parsed["actions"]
                    if isinstance(parsed.get("envelope"), dict):
                        envelope_obj = parsed["envelope"]
                    break
            except json.JSONDecodeError:
                pass

        envelope = parse_envelope(text, envelope_obj=envelope_obj)

        # Summary priority: structured one_liner, else last non-empty line
        # (the legacy heuristic — weakest field in the old system)
        summary = envelope.get("one_liner")
        if not summary:
            lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
            summary = lines[-1] if lines else "No summary"

        return {
            "reasoning": text,
            "actions": actions,
            "summary": summary[:200],
            "envelope": envelope,
        }

    @staticmethod
    def _is_market_hours() -> bool:
        """Check if US equities markets are currently open (approximate ET check)."""
        now = datetime.now(timezone(timedelta(hours=-4)))  # ET (ignores DST edge)
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close
