# Recon: Structured Judgments + Append-Only Research Data

Generated: 2026-07-11
Status: Recon only — no code changes made
Context read: TIER_ARCHITECTURE.md, RECON_MULTI_SLEEVE_ARCHITECTURE.md, docs/ADR.md (esp. ADR-014/017/019/022)

---

## Change 1: Structured judgments alongside prose

Proposed envelope:
```json
{ "verdict": "...", "one_liner": "...", "factors": [{"signal": "...", "direction": "...", "weight": 0.0}], "confidence": 0.0, "full_text": "..." , "schema_version": 1 }
```

### 1.1 Corrections to the proposal's assumptions

Two of the four sites named in the proposal are **not LLM prose**:

- **`tier2a_prefilter` writes no LLM text.** It is deliberately mechanical (`agents/tier2a_prefilter.py:9` — "No LLM calls. Pure mechanical"). Its `name_observations.analysis` JSONB is already structured (`signals`, `signals_fired`, `total_score`, `amplification_applied`, `reason`, `config_version` — written at `tier2a_prefilter.py:800-826`). Only **tier2b** injects LLM prose into those rows.
- **`journal_entries` contain no LLM prose.** `agents/trade_journal.py:118` writes purely structured trade/market-context fields; `exit_reason` is an enum-ish string. Excluded.

Also excluded after verification: the morning briefing (`services/briefing_service.py:5` — "NO LLM — pure data assembly"; it concatenates playbook + reflection prose, so it inherits any upstream fix), `signal_learner` weight updates, `broker_reconciliation` reports, `performance_insights`, and `proposals.rationale` (programmatic f-string, `agents/lead_agent.py:1995-1999`) — all programmatic, already structured, or both.

### 1.2 Write-site inventory (LLM judgments → DB)

| # | Site | Write location | What / where stored | Current structure | Dashboard-facing? | Blast |
|---|------|----------------|---------------------|-------------------|-------------------|-------|
| 1a | Lead agent cycle reasoning | `agents/lead_agent.py:1331` → `services/research_data.py:76` | GLM-5.2 full reasoning → `cycle_snapshots.reasoning` (Text); last-line summary → `.summary`; `{tool_calls, actions}` → `.full_context` JSONB | Prose + partial JSONB; structured cost/model cols already exist (`models/cycle_snapshot.py:40-49`) | YES — `/dashboard/cycles` (`api/routes/dashboard.py:290-309`) → `HistoryPage.jsx:424`; also `api/routes/research.py:249-263` | **M–L** |
| 1b | Sleeve orchestrator cycle | `agents/sleeve_orchestrator.py:599-620` → same `research_data.py:76` | Per-sleeve reasoning concatenated `"=== {sid} ==="` into ONE `reasoning` blob; per-sleeve one-liners joined into `summary`; `full_context` = `{sleeves, actions, risk_rejected, elapsed_seconds}` | Concatenation destroys per-sleeve structure at rest | Same readers as 1a | (in 1a) |
| 2 | Lead-Agent execution log | `agents/lead_agent.py:1305-1313` | Same reasoning duplicated: `execution_logs.rationale` (Text, [:8000]), `order_status`=summary[:200] | Pure Text | Read by `api/routes/intelligence.py:165-190` but **no dashboard/src consumer** — legacy | **S** |
| 3 | Tier 2b per-name reasoning | `agents/tier2b_reasoning.py:339-345` (JSONB mutation + `flag_modified`) | Llama-3.3-70B ≤500-char narrative → `name_observations.analysis["tier2b_reasoning"]`; on failure writes `"reasoning_failed: ..."` marker (`:166-169,311`) | One flat string key inside otherwise-mechanical JSONB | YES — funnel endpoint (`api/routes/dashboard.py:155-176`) → `CommandCenterPage.jsx:221,239`; + `research.py:114-118`; + research_analyst + chat agent | **M** |
| 4 | Playbook entries (3 writers) | Lead tool: `agents/lead_agent.py:968-976`; Chat: `agents/chat_agent.py:389-397`; Weekly/Monthly digests: `weekly_summarizer.py:102-111` / `monthly_summarizer.py:101-110` | Prose → `playbook_entries.content` (Text) | Table already carries partial envelope (`category`, `source`, `confidence`, `validated`, `trades_supporting`, `active`) but **no JSONB column** | YES — `/dashboard/playbook` → HistoryPage PlaybookPanel; + briefing + lead `get_playbook` tool + summarizer feedback loops + embeddings | **L** |
| 5 | Research Analyst reflection | `agents/research_analyst.py:107-115` | Llama-3.3 3–5 paragraph narrative → `agent_messages.body`, `message_type="daily_reflection"` | Pure Text; **`payload` JSONB exists and is unused** (`models/agent_message.py:27`) | YES — `/dashboard/reflection` → CommandCenterPage ReflectionPanel | **M** |
| 6 | Fundamentals summaries | `agents/fundamentals_analyst.py:175-183` | Llama-3.3 3–5 sentence summary → `agent_messages.body`, doubles as 24h cache | Pure Text; `payload` unused | NO — only reader is lead `get_fundamentals` tool (`lead_agent.py:700,1027`) | **S** |
| 7 | Sleeve action summaries | `agents/sleeve_orchestrator.py:189` → `:635` | Per-sleeve LLM `summary[:200]` nested in `agent_actions.payload` JSONB | JSONB, LLM one-liners inside mechanical stats | NO | **S** (free if #1 carries envelope) |
| 8 | Reasoning embeddings excerpt | `services/embeddings.py:63-71` | 500-char excerpt of embedded prose → `reasoning_embeddings.text_excerpt` | Derived index — follows source tables | NO | **S** |

**Gap found, not retrofit:** the sleeve **conflict resolver** (`sleeve_orchestrator.py:410-474`, ad-hoc Llama client at `:449-452`) makes an LLM judgment (which sleeve wins a symbol collision) that is **never persisted** — only `logger.info` (`:466,530,536`). An envelope write to `agent_actions` here is net-new observability, arguably the most research-valuable single addition (it's a decision that changes which trades happen).

### 1.3 LLM client & parse style per agent (where text originates)

| Agent | Client | Model | Parse style |
|---|---|---|---|
| Lead agent | shared `LLMService` (`services/llm_service.py:52-55`) | `zai-org/GLM-5.2` (`config/settings.py:25`) | tool loop; final text → `_parse_decision` json-block regex (`llm_service.py:363`); **summary = last non-empty line[:200] (`:377`) — the weakest judgment field in the system** |
| Sleeves ×4 | same `LLMService` via `lead.llm_service` (`sleeve_orchestrator.py:328,356`) | GLM-5.2 | same `_parse_decision`; prompt demands ```` ```json ```` action array (`:400-408`) |
| Tier 2b | own AsyncOpenAI (`tier2b_reasoning.py:53-56`) | Llama-3.3-70B (`config/tier2b.yaml:3`) | JSON array → regex → failure-marker (3-level fallback, `:264-313`) |
| Research analyst | own (`:59-62`) | Llama-3.3-70B | raw completion, no parse |
| Fundamentals | own (`:53-56`) | Llama-3.3-70B | raw completion, no parse |
| Weekly / Monthly summarizers | own (`:62-65` / `:61-64`) | Llama-3.3-70B | raw completion, no parse |
| Chat agent | own (`chat_agent.py:138-141`) | DeepSeek-V3 (Llama fallback) | `_extract_actions` fenced/bare-JSON regex (`:238-262`) |
| Conflict resolver | ad-hoc per call (`sleeve_orchestrator.py:449-452`) | Llama-3.3-70B | single-word substring match (`:459-467`) |

All prose producers are OpenAI-protocol on Together AI. Embeddings (`text-embedding-3-small`) is the only true-OpenAI client.

### 1.4 Where to enforce the schema (least duplication)

**Recommendation: one shared Pydantic `JudgmentEnvelope` model + a module-level `parse_envelope(text) -> JudgmentEnvelope` helper in `services/llm_service.py`** (importable without instantiating `LLMService`). Not per-agent prompt-only, not hard `response_format` everywhere.

Reasoning:

1. **Coverage math.** The GLM-5.2 path (lead + all 4 sleeves = sites 1a, 1b, 2, 7) funnels through the single `_parse_decision` at `llm_service.py:354` — one change covers four sites. The five independent prose writers share the identical `client.chat.completions.create → choices[0].message.content` shape; adopting `parse_envelope()` is ~5 lines per agent.
2. **Prompt pattern: "prose, then a fenced ```json envelope block."** This is exactly what `_parse_decision` and chat's `_extract_actions` already do — the helper unifies existing convention rather than inventing one. Forcing whole-response JSON (`response_format={"type":"json_object"}`) would degrade the long-form reflections/digests the system depends on; it IS appropriate for the short-output sites (tier2b, fundamentals, conflict resolver).
3. **Fallback semantics that can never lose data:** on parse failure, `full_text` is always populated and the envelope fields are null + `schema_version` marks it degraded — mirroring tier2b's proven 3-level fallback.
4. **The cleanest existing mechanism is tool-call arguments.** The lead agent's `add_playbook_entry` tool already receives `category/content/confidence` as structured arguments (`lead_agent.py:901-903,973`). Extending that tool's `input_schema` with `verdict/one_liner/factors` is the lowest-risk first migration, and a forced `submit_decision` tool for the lead cycle is the natural end state.

### 1.5 Migration impact

Old rows can stay prose-only with **zero backfill**:

- `cycle_snapshots.full_context`, `name_observations.analysis`, `agent_messages.payload`, `agent_actions.payload` are **existing JSONB** — the envelope lands as a new key (`envelope` / `tier2b_envelope`) with no Alembic migration at all. Absence of the key = legacy row. A `schema_version` field *inside* the envelope beats a table column (no migration, versioned per-judgment).
- `playbook_entries` is the one table needing a migration (no JSON column):
  ```python
  # alembic: add envelope to playbook_entries
  op.add_column("playbook_entries", sa.Column("envelope", postgresql.JSONB(), nullable=True))
  ```
  Nullable — old rows stay prose-only, readers treat NULL as `schema_version=0`.
- `execution_logs` cycle rows (site 2) should be **retired, not retrofitted** — they duplicate `cycle_snapshots.reasoning` byte-for-byte and have no live dashboard consumer.

### 1.6 Blast radius summary

| Size | Sites | Why |
|---|---|---|
| S | 2 (retire), 6, 7, 8, conflict resolver (net-new) | one writer / one or zero readers; JSONB ready |
| M | 3 (tier2b), 5 (reflection) | multiple readers; prompt change; JSONB ready |
| M–L | 1 (cycle snapshots, both writers) | shared parser change + 3 reader surfaces; per-sleeve envelope list in `full_context` should replace the `=== sid ===` blob |
| L | 4 (playbook) | 3 writers × 3 parse styles, ~6 readers, needs migration |

---

## Change 2: Append-only observation/analysis tables

Schedule context for the timing arguments below (`main.py:172-430`, ET): 08:00 tier-1 sweep → 10:00/12:00/14:00 tier-2a sweeps → :10 tier-2b reasoning → :20 Lead cycles (trades) → 17:00 outcome labeler → 17:15 signal learner.

### 2.1 Correction to the proposal's assumption — the real mechanic is worse

The reported case ("tier2a overwriting `name_observations.analysis` written earlier the same day") is confirmed, but the mechanism is **row deletion, not JSONB overwrite**:

**`agents/tier2a_prefilter.py:333-340` deletes ALL tier-2 rows for the day** (`delete(NameObservation).where(tier==2, timestamp>=today_start)`) and re-inserts fresh rows (`:344`, `_write_observations` `:803-826`) — three times a day. Each sweep therefore destroys:
- the `tier2b_reasoning` that tier-2b wrote into those rows 10 minutes after the *prior* sweep, and
- the exact signal snapshot the Lead Agent traded on at :20.

**Training-path impact is HIGH.** A trade decided at 10:20 references the 10:00 observation. At 12:00 that row is gone. At 17:00, `outcome_labeler._find_observation` (`services/outcome_labeler.py:431-452`) picks the *latest* tier-2 `was_considered=True` row with `timestamp <= trade_date+1d` — no lower bound, `order_by desc, limit 1`. So the frozen `signal_profile` (the signal learner's ground truth, `services/signal_learner.py:174-178`) can be: the 14:00 sweep's different signal values; a **prior day's** row if the symbol didn't re-pass; or nothing — silently flipping `funnel_driven` to False. This directly poisons the 10/50 learning funnel.

### 2.2 Mutation-site inventory

| # | Site | Table.columns | Trigger | Destructive? | Feeds training? |
|---|------|---------------|---------|--------------|-----------------|
| 1 | `agents/tier2a_prefilter.py:333-344` | `name_observations` — whole tier-2 rows (DELETE+reinsert) | 3×/day + manual | **YES** — rows + tier2b reasoning + traded-on snapshots destroyed | **YES — the headline hazard** (§2.1) |
| 2 | `agents/tier2b_reasoning.py:329-345` | `name_observations.analysis["tier2b_reasoning"]` in-place JSONB mutation + `flag_modified` | 3×/day :10 | Yes — replaces prior value; failure path (`:164-169`) can replace good reasoning with `"reasoning_failed"` marker | Yes — frozen into `signal_profile` at label time |
| 2b | same select `:329-336` | — | — | `.limit(1)` with **no `order_by`** — nondeterministic row choice if duplicates exist; tier2b at :10 can also observe a partially-written tier2a sweep | Yes |
| 3 | `agents/breadth_analyst.py:331-344` | `name_observations` tier-1 rows (DELETE+reinsert) | daily 08:00 | Yes on same-day re-run | Indirect (tier2a reads today's tier-1 passes, `tier2a_prefilter.py:107-119`) |
| 4 | `services/tier_writer.py:44-49` | identical tier-1 DELETE+reinsert | manual (`scripts/run_universe_sweep.py:48`) | Yes — duplicate implementation of #3 (drift risk) | Indirect |
| 5 | `scripts/repair_outcome_data.py:62-72` | `trades.status` bulk update; **`trade_outcomes` full DELETE** + relabel; embeddings delete | manual | **YES** — relabel regenerates `signal_profile` from whichever observations *survive today*; every run launders history | **YES** |
| 6 | `agents/worker_wheel.py:141-174` | `wheel_states` — select-then-mutate upsert of `state, original_cost, total_premium_collected, cycle_count` | every `set_state` (`:187`) AND `_add_premium` (`:213`) — one transition = two writes | Yes — current-state only, no transition history; in-memory running total (`:202`) corrupts on restart/dual-instance; insert race → IntegrityError **swallowed by bare except** `:173-174` (write silently lost) | No (but the observed double-write class) |
| 7 | `agents/base_agent.py:57-76` | `worker_states.is_active, paused_reason` upsert | pause/resume via API | Yes — prior reason/actor/time lost; race → swallowed IntegrityError `:75-76` | No |
| 8 | `services/order_reconciler.py:81-92` | `trades.status→filled, price→fill_price, notes` | every Lead cycle | Semi — by design (labeler depends on fill in `price`; limit survives in `premium`). **Bug: `filled_at` parsed at `:73-79` then never persisted** — fill timestamps permanently lost | **YES** — fill prices feed PnL labels |
| 9 | `services/order_reconciler.py:100-116` | `trades.status→rejected/cancelled/order_expired, notes` | every Lead cycle | Notes append preserves trail; no status-transition history | Yes (status gates labeling) |
| 10 | `agents/trade_journal.py:158-206` `log_exit` | `journal_entries` exit fields | worker closes + reconciler | **Effectively write-once** — query filters `exit_at IS NULL`, second caller no-ops. Low risk (only which racing caller wins) | Marginal |
| 11 | `agents/lead_agent.py:2087-2188` | `proposals.status` + timestamps (approve/reject/batch) | per user action | Transitions w/ timestamps, no history — acceptable | No |
| 12 | `agents/lead_agent.py:2194-2260` `modify_proposal` | `proposals.contracts/strike/delta/premium` overwritten in place | per user action | **YES** — LLM's original terms lost; "human-modified vs as-proposed" analysis impossible | Research-relevant |
| 13 | `api/routes/proposals.py:179-191` `reset_proposal` | `proposals.status→pending`, **nulls `approved_at/executed_at/rejected_at`** | per user action | **YES** — decision history erased | Research-relevant |
| 14 | `agents/chat_agent.py:434-438` | `playbook_entries.active→False` | chat action | Soft-delete, content kept; no `deactivated_at`/actor | No |
| 15 | Manual scripts: `clean_ghost_trades.py:52-57`, `mark_legacy_submitted_unknown.py:48-54`, `backfill_agent_assignments.py:61-66` | bulk `update(Trade)` | manual | Yes — esp. agent_name overwrite changes attribution of already-labeled outcomes | Yes |

**Verified append-only (no fix needed):** `scanner_opportunities` (`agents/scanner.py:627-657`), `cycle_snapshots` (`research_data.py:52-79`), `equity_snapshots` (`main.py:29-43`), `regime_snapshots` (`market_regime.py:405-424`), `pending_changes`, and the outcome labeler's own writes (insert-only, pre-check + `uq_trade_outcomes_trade_id`). `agent_performance` has **no writers anywhere** — dead table. `positions` is mutated in place (`services/logger_service.py:79-102`) — live-state table, low research priority. Note **`skill_documents` already implements append-only versioning** (`research_data.py:168-194`, `uq_skill_doc_agent_version(agent_name, version)`) — the house precedent for pattern (b).

Key structural fact: `trade_outcomes.signal_profile` already implements **freeze-at-use** — but the freeze happens at 17:00, ~7 hours after the intraday deletes. The snapshot pattern is right; its timing is wrong.

### 2.3 Existing unique constraints (proposals must not clash)

| Table | Unique | Notes |
|---|---|---|
| name_observations | **none** | ix on timestamp, symbol, tier, (symbol,timestamp), cycle_snapshot_id |
| trade_outcomes | `uq_trade_outcomes_trade_id` | must be replaced if revisions added |
| wheel_states | `ix_wheel_states_symbol` UNIQUE | enables ON CONFLICT upsert |
| worker_states | `UniqueConstraint(worker_name)` | enables ON CONFLICT upsert |
| agent_performance | `uq_agent_performance_date` | dead table |
| skill_documents | `uq_skill_doc_agent_version` | append-only precedent |
| proposals, trades, journal_entries, cycle/equity/regime snapshots | none unique | trades.order_id indexed non-unique |

### 2.4 Smallest fix per site (with Alembic sketches)

**Site 1+2 — two-part fix (the headline):**

(d) *Freeze-at-decision* — copy the observation onto the trade at Lead-cycle time; labeler's `_find_observation` becomes fallback-only:
```python
op.add_column('trades', sa.Column('name_observation_id', sa.Integer(), nullable=True))
op.add_column('trades', sa.Column('signal_snapshot', sa.JSON(), nullable=True))
```
(b) *Append-only sweeps* — drop the `delete()` at `tier2a_prefilter.py:333`; stamp each sweep:
```python
op.add_column('name_observations', sa.Column('sweep_id', sa.String(36), nullable=True))
op.create_index('ix_name_observations_sweep_id', 'name_observations', ['sweep_id'])
op.create_unique_constraint('uq_nobs_sweep_symbol_tier', 'name_observations', ['sweep_id', 'symbol', 'tier'])
```
Readers (tier2b `:114-120`, sleeve_orchestrator `:228-236`, labeler `:436-444`, dashboard funnel) switch from `timestamp >= today` to "latest sweep_id". The unique constraint also delivers real idempotency: a re-run with the same sweep_id conflicts instead of silently duplicating.

**Site 2 —** stop mutating `analysis`; dedicated columns keep tier2a's snapshot immutable, plus deterministic `order_by` on the select, and never overwrite good reasoning with a failure marker (write only when NULL):
```python
op.add_column('name_observations', sa.Column('tier2b_reasoning', sa.Text(), nullable=True))
op.add_column('name_observations', sa.Column('tier2b_reasoned_at', sa.DateTime(timezone=True), nullable=True))
```

**Sites 3/4 —** same `sweep_id` covers tier-1; remove both delete blocks; consolidate to one writer.

**Site 5 —** revisioned outcomes instead of wholesale delete:
```python
op.add_column('trade_outcomes', sa.Column('revision', sa.Integer(), server_default='1', nullable=False))
op.drop_constraint('uq_trade_outcomes_trade_id', 'trade_outcomes')
op.create_unique_constraint('uq_trade_outcomes_trade_rev', 'trade_outcomes', ['trade_id', 'revision'])
```
Repairs insert revision N+1; learner reads max-revision; original `signal_profile`s preserved forever.

**Site 6 —** (c) event side-table + close the race with `INSERT ... ON CONFLICT (symbol) DO UPDATE` (unique index already exists); totals become recomputable from events:
```python
op.create_table('wheel_state_events',
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('symbol', sa.String(), nullable=False, index=True),
    sa.Column('from_state', sa.String(32)), sa.Column('to_state', sa.String(32)),
    sa.Column('premium_delta', sa.Float()), sa.Column('total_premium_after', sa.Float()),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()))
```

**Site 7 —** minimum viable: ON CONFLICT upsert + `changed_at` column; fuller: a `worker_state_events` twin of the above.

**Site 8 —** stop reusing `price`; new columns fix the dropped-`filled_at` bug in the same stroke:
```python
op.add_column('trades', sa.Column('fill_price', sa.Float(), nullable=True))
op.add_column('trades', sa.Column('filled_at', sa.DateTime(timezone=True), nullable=True))
```
Reconciler writes `fill_price`/`filled_at`; `price` stays the limit; labeler's chain becomes `fill_price or price`.

**Site 12 —** freeze original terms on first modify: `op.add_column('proposals', sa.Column('original_terms', sa.JSON(), nullable=True))`

**Site 13 —** append `{status, at}` transitions instead of nulling timestamps: `op.add_column('proposals', sa.Column('status_history', sa.JSON(), server_default='[]'))`

**Site 14 —** optional: `deactivated_at` column.

---

## Also: other data-integrity / observability findings

### A. Order-reconciler fill-price drift (confirmed mechanics)

The observed "DB fill prices differ from broker fills" has three concrete mechanisms:

1. **Partial fills are silently lost.** `services/order_reconciler.py` only processes `status="submitted"` trades and its expired/cancelled branch (`:100-118`) never inspects `filled_qty` — which `broker.get_order()` returns (`services/alpaca_broker.py:722`). An order that partially fills then expires is stamped `order_expired` with the partial fill erased from trade history. The trade also exits the `submitted` state permanently, so it is never re-checked.
2. **Silent limit-price fallback.** `order_reconciler.py:87` — `price=fill_price or trade.price`: a falsy `filled_avg_price` from Alpaca leaves the submission limit price masquerading as a fill with no marker.
3. **`trades.pnl` on close legs is a quote-time estimate, never trued up.** Workers compute `realized_pnl` from `pos.current_price` at submission (`worker_csp.py` `_close_position`) and write it to `trades.pnl`; the reconciler later updates `price` to the real fill but never recomputes `pnl`. The outcome labeler now prefers fill prices, but every direct reader of `trades.pnl` still sees the stale estimate.

Smallest fixes: (1) reconcile terminal statuses with `filled_qty > 0` as partial fills (record qty + fill price, status `partially_filled`); (2) `price=fill_price if fill_price is not None else trade.price` plus a note marker when falling back; (3) recompute `pnl` in the reconciler's fill branch for `buy_to_close` rows using the fill price.

### B. In-place mutation of live-state tables

`services/logger_service.py:70-104` (`log_position_update`) mutates `positions` rows in place (price/status/pnl). Acceptable for live state, but there is no history of position-health trajectory — the `position_sentinel` alerts read current state only. If trajectory ever matters for research (e.g., "was this position ever >50% underwater before winning?"), an event-log side table is the fix; low priority otherwise.

### C. Un-persisted judgments

Sleeve conflict-resolution verdicts (see §1.2) — LLM decisions that alter which trades execute, currently existing only in container logs with no DB record.

---

## Ranked recommendations (value to research integrity ÷ effort)

| Rank | Change | Value | Effort | Rationale |
|------|--------|-------|--------|-----------|
| 1 | **Freeze-at-decision snapshot on trades** (Change 2, site 1 fix d) | Very high | ~½ day (2 columns + copy at Lead-cycle + labeler fallback) | Directly stops mislabeled `signal_profile`s and `funnel_driven` flapping — protects the 10/50 learning funnel *today*, independent of any sweep refactor |
| 2 | **Fix reconciler fill recording** (Change 2 site 8 + Also §A) | High | ~½ day | `fill_price`/`filled_at` columns; persist the already-parsed `filled_at`; handle partial fills; recompute BTC `pnl` on fill. Every PnL label depends on this path |
| 3 | **Append-only sweeps via `sweep_id`** (Change 2, sites 1/3/4 fix b) | High | ~1–2 days (migration + ~5 reader queries) | Kills the 3×/day history destruction; gives idempotent re-runs via unique constraint; preserves tier2b reasoning |
| 4 | **Tier2b dedicated columns + never-overwrite guard** (site 2) | High | ~½ day | Ends JSONB mutation of the mechanical snapshot; deterministic select; failure markers stop destroying good reasoning |
| 5 | **Envelope in the shared GLM path** (Change 1, sites 1a/1b/2/7 via `parse_envelope` in `llm_service.py`) | High | ~1 day | One parser change structures the lead + all 4 sleeves; replaces the brittle "summary = last line"; per-sleeve envelope list ends the `=== sid ===` blob; zero migration (JSONB exists) |
| 6 | **Revisioned trade_outcomes** (site 5) | Medium-high | ~½ day | Repair scripts stop laundering label history; cheap insurance for every future audit |
| 7 | **Persist conflict-resolver verdicts** (Change 1 §1.2 gap) | Medium-high | ~2 hours | An LLM judgment that changes which trades execute currently lives only in container logs |
| 8 | **Wheel/worker state events + ON CONFLICT upsert** (sites 6/7) | Medium | ~1 day | Closes the observed double-write/race class; makes premium totals recomputable |
| 9 | **Envelope for tier2b + reflection** (Change 1 sites 3/5) | Medium | ~1 day | Highest-traffic dashboard prose; JSONB/`payload` columns already exist |
| 10 | **Proposal history integrity** (sites 12/13) | Medium | ~2 hours | `original_terms` + `status_history`; enables human-vs-agent modification research |
| 11 | **Envelope for playbook** (Change 1 site 4) | Medium-low | ~2 days | 3 writers × 3 parse styles + migration; do last, after the helper exists and is proven |
| 12 | **Retire Lead-Agent execution_log duplicate** (Change 1 site 2) | Low | ~1 hour | Byte-for-byte duplicate of cycle_snapshots with no dashboard consumer |
| 13 | Envelope for fundamentals / digests; playbook `deactivated_at`; position-health event log | Low | opportunistic | Internal-only readers or optional history |

**Suggested sequencing:** 1+2 together (both touch the trade write path; both protect labels), then 3+4 (one migration PR ends destructive sweeps), then 5 (envelope core), then the rest opportunistically. Items 1–4 are prerequisites for trusting the signal-weight learner's first training run at n=50 — shipping them before the funnel fills is materially cheaper than re-labeling after.
