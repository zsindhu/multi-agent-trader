"""
RAG Chat Agent — Natural language interface for querying all system data.

Classifies user queries, generates SQL or semantic searches, executes them,
then sends results + question to an LLM for analysis and response.

Model: DeepSeek V3 on Together AI (~$0.50/month at 20 queries/day).
Fallback: Llama 3.3 70B if DeepSeek unavailable.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import text as sql_text

from config.settings import settings
from core.database import AsyncSessionLocal
from models.playbook_entry import PlaybookEntry
from services.context_retrieval import ContextRetrievalService

MODEL = "deepseek-ai/DeepSeek-V3"
FALLBACK_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

# Schema context injected into system prompt so the LLM knows exact table/column names
SCHEMA_CONTEXT = """
## Database Schema

### trades
Columns: id, agent_name, symbol, option_symbol, trade_type (sell_to_open/buy_to_close/buy_to_open/sell_to_close), side (buy/sell), quantity, price, premium, strike, expiration, status (filled/expired/closed/assigned/cancelled), pnl, notes, order_id, created_at, closed_at

### trade_outcomes (ground truth — one row per completed trade)
Columns: id, trade_id (FK→trades), name_observation_id (FK→name_observations), funnel_driven (bool), sleeve_id, outcome (win/loss/breakeven/pending), pnl_dollars, pnl_percent, holding_days, underlying_return, signal_profile (JSONB: {signals: {signal_name: {fired, raw, z_score}}}), estimated_edge, labeled_at

### name_observations (Tier 1-2 scanning funnel)
Columns: id, timestamp, cycle_snapshot_id, symbol, sleeve_id, tier (1=universe/2=promoted), price, daily_volume, market_cap, iv_rank, composite_score, avg_volume_20d, avg_volume_60d, asset_type, selection_reason, was_considered (bool), was_traded (bool), rejection_reason, analysis (JSONB: {signals: {...}, tier2b_reasoning: "...", amplification_applied: float})

### cycle_snapshots (Lead Agent execution state per cycle)
Columns: id, timestamp, regime, regime_confidence, vix_level, vix_direction, breadth_pct, spy_trend, credit_stress, equity, cash, buying_power, open_positions_count, unrealized_pnl, actions_decided, actions_executed, summary, reasoning, llm_tokens_in, llm_tokens_out, llm_cost_usd, llm_model, full_context (JSONB: {tool_calls, actions})

### playbook_entries (institutional memory)
Columns: id, category (strategy_rule/lesson_learned/parameter_adjustment/symbol_note/regime_observation/market_insight/weekly_digest/monthly_digest), content, source, confidence (0-1), validated (bool), trades_supporting, created_at, superseded_by, active (bool)

### strategy_insights (structured enforceable rules)
Columns: id, insight_type, rule, parameters, confidence, supporting_trades, contradicting_trades, win_rate_with, win_rate_without, discovered_at, last_validated, active (bool)

### agent_messages (inter-agent communication)
Columns: id, timestamp, sender, recipient, message_type (daily_reflection/daily_briefing), subject, body, payload (JSONB), read_by_lead_agent, expires_at

### llm_usage_log (cost tracking)
Columns: id, timestamp, model, caller, tokens_in, tokens_out, cache_read, cache_create, cost_usd, cycle_id

### historical_bars (daily price data, 3M+ rows)
Columns: id, symbol, bar_date, open, high, low, close, volume, vwap, source

### journal_entries (trade journal with entry/exit context)
Columns: id, agent_name, symbol, contract_type, strike, expiration, side, quantity, fill_price, premium, entry_iv_rank, entry_stock_price, entry_vix_level, delta_at_entry, dte_at_entry, annualized_return_at_entry, exit_stock_price, exit_reason, realized_pnl, days_held, return_pct, entry_at, exit_at

### pending_changes (change proposal pipeline)
Columns: id, created_at, change_type, description, proposed_config (JSONB), current_config (JSONB), backtest_result (JSONB), status (proposed/backtested/approved/applied/rejected), reviewed_at, reviewer_notes

### earnings_events
Columns: id, symbol, event_type, event_date, days_until, risk_level, fetched_at

### equity_snapshots
Columns: id, equity, cash, buying_power, recorded_at

## Key relationships
- trade_outcomes.trade_id → trades.id
- trade_outcomes.name_observation_id → name_observations.id
- name_observations.cycle_snapshot_id → cycle_snapshots.id
"""

SYSTEM_PROMPT = f"""You are a research assistant for an automated options trading system called Premium Trader. You help the operator understand the system's decisions, performance, and strategy by querying databases and providing analysis.

{SCHEMA_CONTEXT}

## Your capabilities

1. **SQL queries**: Generate and execute read-only SELECT queries against any table above. Always use the exact column names from the schema.

2. **Semantic search**: Search playbook entries, trade outcomes, and cycle reasoning by meaning using embedding similarity.

3. **Write-back**: Write new strategy rules or insights to the playbook. Only for category: strategy_rule, lesson_learned, parameter_adjustment, symbol_note, market_insight.

4. **Analysis**: Fetch data and provide interpretation — patterns, anomalies, comparisons, recommendations.

## Response format

When you need to query data, output a JSON action block:

```action
{{"type": "sql", "query": "SELECT ..."}}
```

```action
{{"type": "semantic", "query": "earnings losses patterns"}}
```

```action
{{"type": "write_playbook", "category": "strategy_rule", "content": "Never sell puts within 3 days of earnings", "confidence": 0.7}}
```

```action
{{"type": "deactivate_playbook", "entry_id": 42}}
```

After receiving query results, provide a clear, specific answer. Include numbers, dates, and symbol names. If the data doesn't support an answer, say so.

## Rules
- ONLY generate SELECT queries — never INSERT, UPDATE, DELETE, DROP, or ALTER
- Limit results to 100 rows max
- When querying JSONB fields, use PostgreSQL JSONB operators: analysis->>'tier2b_reasoning', analysis->'signals'->signal_name->>'fired'
- For time filters use: timestamp >= NOW() - INTERVAL '7 days'
- Always qualify ambiguous column names with table aliases
- Be concise but specific in your analysis"""


class ChatAgent:
    """RAG Chat Agent — natural language queries over all system data."""

    def __init__(self):
        self._client = None
        self._model = MODEL
        self._enabled = False
        self._retrieval = ContextRetrievalService()
        self._init_client()

    def _init_client(self):
        if not settings.together_api_key:
            logger.warning("[Chat] Disabled — no TOGETHER_API_KEY")
            return
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.together_api_key,
                base_url="https://api.together.xyz/v1",
            )
            self._enabled = True
        except Exception as e:
            logger.error(f"[Chat] Client init failed: {e}")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def chat(self, message: str, history: list[dict] = None) -> dict:
        """
        Process a user message and return a response.

        Args:
            message: User's question
            history: Previous messages [{"role": "user"/"assistant", "content": "..."}]

        Returns:
            {"response": str, "data": Optional[dict], "actions_taken": list}
        """
        if not self._enabled:
            return {"response": "Chat agent is disabled — no TOGETHER_API_KEY configured.", "data": None, "actions_taken": []}

        history = history or []
        actions_taken = []

        # Build messages for first LLM call — classify + plan
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        # First LLM call: understand query, generate action plan
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=1500,
                temperature=0.2,
            )
            plan_text = response.choices[0].message.content.strip()
        except Exception as e:
            # Try fallback model
            try:
                self._model = FALLBACK_MODEL
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=1500,
                    temperature=0.2,
                )
                plan_text = response.choices[0].message.content.strip()
            except Exception as e2:
                logger.error(f"[Chat] LLM call failed: {e2}")
                return {"response": f"LLM call failed: {e2}", "data": None, "actions_taken": []}

        # Extract and execute action blocks
        actions = self._extract_actions(plan_text)
        context_parts = []

        for action in actions:
            try:
                result = await self._execute_action(action)
                actions_taken.append({"action": action, "result": result})
                context_parts.append(f"Query result:\n{json.dumps(result, default=str, indent=2)[:3000]}")
            except Exception as e:
                actions_taken.append({"action": action, "error": str(e)})
                context_parts.append(f"Query error: {e}")

        # If actions were executed, make a second LLM call for final analysis
        if context_parts:
            messages.append({"role": "assistant", "content": plan_text})
            messages.append({"role": "user", "content": "Here are the results:\n\n" + "\n\n".join(context_parts) + "\n\nNow provide your analysis and answer."})

            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=1500,
                    temperature=0.3,
                )
                final_response = response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"[Chat] Analysis LLM call failed: {e}")
                final_response = plan_text  # Fall back to first response
        else:
            final_response = plan_text

        # Clean action blocks from final response for display
        clean_response = re.sub(r'```action\n.*?\n```', '', final_response, flags=re.DOTALL).strip()

        return {
            "response": clean_response or final_response,
            "data": actions_taken[-1]["result"] if actions_taken and "result" in actions_taken[-1] else None,
            "actions_taken": [a["action"] for a in actions_taken],
        }

    def _extract_actions(self, text: str) -> list[dict]:
        """Extract ```action {...}``` blocks from LLM output."""
        actions = []
        pattern = r'```action\s*\n(.*?)\n```'
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                action = json.loads(match.group(1).strip())
                actions.append(action)
            except json.JSONDecodeError:
                continue
        return actions

    async def _execute_action(self, action: dict) -> dict:
        """Execute a classified action and return results."""
        action_type = action.get("type", "")

        if action_type == "sql":
            return await self._execute_sql(action.get("query", ""))

        elif action_type == "semantic":
            query = action.get("query", "")
            results = await self._retrieval.search_all(query, limit=action.get("limit", 5))
            return results

        elif action_type == "write_playbook":
            return await self._write_playbook(
                category=action.get("category", "market_insight"),
                content=action.get("content", ""),
                confidence=action.get("confidence", 0.5),
            )

        elif action_type == "deactivate_playbook":
            return await self._deactivate_playbook(action.get("entry_id"))

        else:
            return {"error": f"Unknown action type: {action_type}"}

    async def _execute_sql(self, query: str) -> dict:
        """Execute a read-only SQL query with safety checks."""
        if not query.strip():
            return {"error": "Empty query"}

        # Safety: only allow SELECT
        normalized = query.strip().upper()
        if not normalized.startswith("SELECT"):
            return {"error": "Only SELECT queries are allowed"}

        dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"]
        for keyword in dangerous:
            if re.search(rf'\b{keyword}\b', normalized):
                return {"error": f"Forbidden keyword: {keyword}"}

        # Force LIMIT if not present
        if "LIMIT" not in normalized:
            query = query.rstrip().rstrip(";") + " LIMIT 100"

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(sql_text(query))
                rows = result.mappings().all()
                return {
                    "columns": list(rows[0].keys()) if rows else [],
                    "rows": [dict(r) for r in rows[:100]],
                    "count": len(rows),
                    "query": query,
                }
        except Exception as e:
            return {"error": f"SQL execution failed: {e}", "query": query}

    async def _write_playbook(self, category: str, content: str, confidence: float = 0.5) -> dict:
        """Write a new playbook entry via the chat agent."""
        allowed = {"strategy_rule", "lesson_learned", "parameter_adjustment", "symbol_note", "market_insight"}
        if category not in allowed:
            return {"error": f"Category '{category}' not allowed. Use: {', '.join(sorted(allowed))}"}

        if not content.strip():
            return {"error": "Content cannot be empty"}

        try:
            async with AsyncSessionLocal() as session:
                entry = PlaybookEntry(
                    category=category,
                    content=content.strip(),
                    source="chat_agent",
                    confidence=confidence,
                )
                session.add(entry)
                await session.commit()
                await session.refresh(entry)

                # Embed for semantic retrieval
                try:
                    from services.embeddings import EmbeddingsService
                    emb = EmbeddingsService()
                    if emb.is_enabled:
                        await emb.embed_and_store(
                            text=f"[{entry.category}] {entry.content}",
                            source_table="playbook_entries",
                            source_id=entry.id,
                        )
                except Exception:
                    pass

                return {"status": "added", "id": entry.id, "category": category}
        except Exception as e:
            return {"error": f"Failed to write playbook entry: {e}"}

    async def _deactivate_playbook(self, entry_id: Optional[int]) -> dict:
        """Deactivate (soft-delete) a playbook entry."""
        if not entry_id:
            return {"error": "entry_id is required"}

        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select as sa_select, update
                result = await session.execute(
                    sa_select(PlaybookEntry).where(PlaybookEntry.id == entry_id)
                )
                entry = result.scalar_one_or_none()
                if not entry:
                    return {"error": f"Playbook entry {entry_id} not found"}
                if not entry.active:
                    return {"status": "already_inactive", "id": entry_id}

                await session.execute(
                    update(PlaybookEntry)
                    .where(PlaybookEntry.id == entry_id)
                    .values(active=False)
                )
                await session.commit()
                return {"status": "deactivated", "id": entry_id, "category": entry.category}
        except Exception as e:
            return {"error": f"Failed to deactivate: {e}"}
