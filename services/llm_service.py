"""
LLM Service — Claude API integration for the Lead Agent's reasoning engine.

Uses Claude's tool use (function calling) to let the LLM query data services
on demand and produce structured trading decisions.

When ANTHROPIC_API_KEY is not set, is_enabled returns False and every call
returns an empty-actions dict — the Lead Agent falls back to rule-based logic.
"""
import json
import re
from datetime import datetime, date, timezone, timedelta
from typing import Optional

import anthropic
from loguru import logger

from config.settings import settings


class LLMService:
    """
    Wraps the Anthropic API for Lead Agent decision-making.

    Defines tools that map to data services, sends them to Claude,
    executes tool calls via the provided executor, and returns a
    structured decision dict.
    """

    MAX_DAILY_COST = 1.00  # Hard cap: $1/day

    def __init__(self):
        self._enabled = bool(settings.anthropic_api_key)
        if self._enabled:
            self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            self.model = settings.llm_model
            self.max_tokens = settings.llm_max_tokens
            logger.info(f"[LLM] Initialized with model {self.model}")
        else:
            self.client = None
            self.model = settings.llm_model
            self.max_tokens = settings.llm_max_tokens
            logger.warning(
                "[LLM] No ANTHROPIC_API_KEY configured — "
                "Lead Agent will fall back to rule-based decisions"
            )
        # Daily usage tracking (resets at UTC midnight)
        self._daily_input_tokens: int = 0
        self._daily_output_tokens: int = 0
        self._daily_cost: float = 0.0
        self._cost_reset_date: date = datetime.utcnow().date()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def get_cycle_decision(
        self,
        tools: list[dict],
        tool_executor,
        portfolio_summary: dict,
        system_prompt: str,
    ) -> dict:
        """
        Run a full Lead Agent reasoning cycle via Claude.

        Args:
            tools: Tool definitions in Claude function-calling format.
            tool_executor: async callable(tool_name, tool_input) → dict
            portfolio_summary: Current portfolio state (always included in context).
            system_prompt: The Lead Agent's identity and constraints.

        Returns:
            {
                "reasoning": str,     # Claude's full reasoning text
                "actions": list[dict], # Specific instructions for workers
                "summary": str,        # One-line summary for the dashboard
            }
        """
        if not self._enabled:
            return {
                "reasoning": "LLM not configured — using rule-based fallback",
                "actions": [],
                "summary": "Rule-based mode (no ANTHROPIC_API_KEY)",
            }

        # Daily spending cap
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

            messages = [{"role": "user", "content": user_message}]
            total_input_tokens = 0
            total_output_tokens = 0

            # Multi-turn tool use loop
            max_turns = 10
            for turn in range(max_turns):
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt,
                    tools=tools,
                    messages=messages,
                )

                self._track_usage(response.usage.input_tokens, response.usage.output_tokens)
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                if response.stop_reason == "tool_use":
                    tool_results = []
                    assistant_content = response.content

                    for block in response.content:
                        if block.type == "tool_use":
                            logger.info(
                                f"[LLM] Tool call: {block.name}"
                                f"({json.dumps(block.input)[:120]})"
                            )
                            try:
                                result = await tool_executor(block.name, block.input)
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps(result, default=str),
                                })
                            except Exception as e:
                                logger.error(
                                    f"[LLM] Tool '{block.name}' failed: {e}"
                                )
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps({"error": str(e)}),
                                    "is_error": True,
                                })

                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append({"role": "user", "content": tool_results})

                else:
                    # Claude is done reasoning — extract the final text
                    final_text = "".join(
                        block.text for block in response.content if hasattr(block, "text")
                    )
                    logger.info(
                        f"[LLM] Cycle complete — "
                        f"{total_input_tokens} in / {total_output_tokens} out tokens "
                        f"| Daily: {self._daily_input_tokens} in / {self._daily_output_tokens} out "
                        f"| Est. cost today: ${self._daily_cost:.4f}"
                    )
                    return self._parse_decision(final_text)

            logger.warning("[LLM] Hit max tool-use turns — no actions taken")
            return {
                "reasoning": "Hit maximum reasoning turns without a final decision.",
                "actions": [],
                "summary": "Reasoning incomplete — no actions taken this cycle",
            }

        except anthropic.APIError as e:
            logger.error(f"[LLM] API error: {e}")
            return {
                "reasoning": f"Anthropic API error: {e}",
                "actions": [],
                "summary": "LLM API error — rule-based fallback active",
            }
        except Exception as e:
            logger.error(f"[LLM] Unexpected error: {e}")
            return {
                "reasoning": f"Unexpected error: {e}",
                "actions": [],
                "summary": "LLM error — rule-based fallback active",
            }

    def _reset_daily_if_needed(self) -> None:
        today = datetime.utcnow().date()
        if today != self._cost_reset_date:
            self._daily_input_tokens = 0
            self._daily_output_tokens = 0
            self._daily_cost = 0.0
            self._cost_reset_date = today

    def _track_usage(self, input_tokens: int, output_tokens: int) -> None:
        self._reset_daily_if_needed()
        self._daily_input_tokens += input_tokens
        self._daily_output_tokens += output_tokens
        # claude-sonnet-4-6: $3/M input, $15/M output
        self._daily_cost += (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0

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
        Parse Claude's final response into a structured decision.

        Looks for a ```json block containing a list of action dicts.
        Falls back to empty actions if no valid JSON block is found.
        """
        actions = []

        json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        for block in json_blocks:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, list):
                    actions = parsed
                    break
                if isinstance(parsed, dict) and "actions" in parsed:
                    actions = parsed["actions"]
                    break
            except json.JSONDecodeError:
                pass

        lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
        summary = lines[-1] if lines else "No summary"

        return {
            "reasoning": text,
            "actions": actions,
            "summary": summary[:200],
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
