# Recon: Pre-Approval Verification for Structured Data Remediation

Generated: 2026-07-11
Status: Recon only — no code changes, no migrations, no DB writes. All SQL below ran read-only against the production Postgres on the droplet (`docker compose exec -T db psql -U premium_trader -d premium_trader`).

---

## Question 1: How contaminated are the existing labels?

### 1a. Exposure counts

```sql
SELECT COUNT(*) AS total_outcomes,
       COUNT(*) FILTER (WHERE funnel_driven) AS funnel_true,
       COUNT(*) FILTER (WHERE outcome IN ('win','loss')) AS win_loss,
       COUNT(*) FILTER (WHERE funnel_driven AND outcome IN ('win','loss')) AS learner_samples,
       COUNT(*) FILTER (WHERE sleeve_id IS NOT NULL) AS with_sleeve
FROM trade_outcomes;
--  total_outcomes | funnel_true | win_loss | learner_samples | with_sleeve
--              17 |          10 |       17 |              10 |           0
```

17 labeled outcomes, 10 funnel-driven learner samples. **`sleeve_id` is populated on zero rows** — the column exists (`models/trade_outcome.py`) but the labeler never sets it, so no per-sleeve breakdown is possible. (This is itself a Block-1-adjacent gap: sleeve attribution of outcomes cannot be reconstructed later either.)

### 1b. Provenance classification

Method: join each outcome to its trade and its stored `name_observation_id`; compare the observation's timestamp to the trade's decision time (`trades.created_at`, naive UTC). Given the DELETE+reinsert mechanic, an observation surviving from the trade's day is the day's *final* sweep; if its timestamp postdates the trade, the labeler joined a sweep the decision never saw.

```sql
SELECT o.id, t.symbol, t.created_at AS trade_at, o.funnel_driven,
       n.timestamp AS obs_at,
       CASE
         WHEN o.name_observation_id IS NULL THEN 'no_observation'
         WHEN n.id IS NULL THEN 'obs_deleted_since'
         WHEN n.timestamp > (t.created_at AT TIME ZONE 'UTC')
              AND n.timestamp::date = t.created_at::date THEN 'wrong_sweep_same_day'
         WHEN n.timestamp::date > t.created_at::date THEN 'wrong_day_after'
         WHEN n.timestamp::date < t.created_at::date THEN 'wrong_day_before'
         ELSE 'plausibly_correct'
       END AS bucket,
       ROUND(EXTRACT(EPOCH FROM (n.timestamp - (t.created_at AT TIME ZONE 'UTC')))/3600, 1) AS gap_hours
FROM trade_outcomes o
JOIN trades t ON t.id = o.trade_id
LEFT JOIN name_observations n ON n.id = o.name_observation_id
ORDER BY t.created_at;
```

Full result (17 rows) summarized:

| Bucket | Count | Rows |
|---|---|---|
| **Verifiably correct** (obs ≤ trade, same day — the day's final sweep, preceding the trade) | **4** | UNP 4/24 (−0.3h), CRM ×3 5/28 (−0.3h) |
| **Provably wrong sweep** (obs postdates decision by 0.8–3.6h) | **6** | CHTR 4/27 (+0.8h), AMGN ×2 5/4 (+3.6h), ETN 5/6 (+1.7h), XLV 6/8 (+3.6h), XLC 6/22 (+3.6h) |
| Wrong day | 0 | — |
| No observation, pre-cutover (correct behavior) | 7 | IWM ×2, XLF ×3, NXE, SRLN — all Apr 10–17, before `FUNNEL_CUTOVER` (Apr 20) |
| Silently flipped funnel_driven | 0 found | all `funnel_driven=false` rows are legitimately pre-cutover |
| Indeterminate | 0 | — |

**6 of the 10 learner samples carry a provably wrong signal_profile** — the stored signals are from the 14:00 ET sweep while the trades were decided at 10:20/12:20/13:16 ET. The wrong-sweep pattern is exactly the predicted mechanic: trades from the day's *final* sweep (14:2x ET fills) classify correct; every earlier-cycle trade joined to the 14:00 sweep's row.

Two aggravating facts:
- **Pseudo-replication:** the 10 samples come from only **7 decision events** — AMGN ×2 share observation 461519 and CRM ×3 share 916978. The learner (`services/signal_learner.py`) treats contracts as independent samples; effective independent decisions are fewer still.
- The wrong-sweep `signal_profile`s are complete, plausible-looking signal dicts (verified: outcome 97 contains full `signals` with scores/raw/fired) — nothing marks them as wrong. Without this recon they'd train the first model silently.

**Can the 6 be reconstructed?** Partially:
- `cycle_snapshots.full_context` holds only `{sleeves, actions, risk_rejected, elapsed_seconds}` (verified on snapshot 189) — **no tool results, no signal values.** No reconstruction path.
- `agent_actions` for tier2a contains only `tier2a_sweep_started/completed` aggregates (270 rows) — no per-name data.
- **Mechanically recomputable as-of decision time:** rules 1, 2, 3, 7 (volume z, range expansion, gap z, correlation breakdown) derive deterministically from `historical_bars`, which retains full coverage for all 5 affected symbols (verified). Rule 8 (earnings proximity) recomputable from `earnings_events`. Rule 4 (IV rank delta) partially — `journal_entries.entry_iv_rank` is populated on all 59 rows for the traded symbol at entry, but the 5-day-ago comparison point is gone. **Not recomputable:** rules 5, 6 (options chain snapshots not stored), 9 (short interest), 10 (news headlines auto-prune at 48h), 11 (social).
- Verdict: a faithful re-label is impossible; a *partial* profile (≈5 of 11 signals) is possible but would give those 6 samples a systematically different feature vector than clean samples — worse than exclusion for a 10-sample dataset.

### 1c. Disposition recommendation

**Exclude the 6 wrong-sweep samples from the first training run; do not re-label; do not down-weight.** Rationale: at n=10, down-weighting is statistical theater; partial re-labeling creates a two-schema feature matrix; exclusion is honest and cheap. Mark them rather than delete (consistent with append-only direction — e.g. the Block-1 `signal_snapshot` work can add a `profile_provenance` flag, or the learner's `_load_data` can carry an exclusion list of the 6 outcome ids: 96, 97, 98, 99, 103, 104).

**Effective clean n = 4 today** (from 2 decision events). Timeline impact: the funnel produced 10 samples in ~9 weeks (Apr 24–Jun 22), ≈1.1/week. At that pace, 46 more clean samples ≈ **10 months to n=50**. Two levers change this materially: (i) the ~55% entry-order miss rate found in the July audit (21 of 59 STOs expired unfilled, 21 cancelled) — fixing limit pricing roughly doubles accrual; (ii) counting *decisions* not contracts will also be necessary for the learner to be honest, which lowers effective n further. **Conclusion: n=50 is a 2027 milestone unless fill-rate work is scheduled; Blocks 1–2 are urgent precisely because nearly all trustworthy training data still lies in the future.**

---

## Question 2: What has repair_outcome_data.py already destroyed?

### 2a. Run count: exactly one

- Git: the script was added in `4a92b26` (2026-07-07, the audit-remediation PR #1); no other commits touch it.
- Data fingerprint: **all 17 `trade_outcomes.labeled_at` values cluster in a single minute** — `2026-07-08 23:43` UTC (SQL above, `date_trunc('minute', labeled_at)` → one group of 17). The nightly 17:00 ET labeler has added zero rows since (no trades have completed since Jul 8).
- Container logs: `docker compose logs app | grep -c '[Repair]'` returns 0 — logs rotated/truncated; the labeled_at cluster and this session's own execution record (the run was performed 2026-07-08 as part of the approved remediation, output logged in that session) are the evidence.

### 2b. What it relabeled, and surviving pre-run records

The single run: reclassified 70 `status='expired'` trades → `order_expired`, deleted **87** pre-existing `trade_outcomes` rows + 43 outcome embeddings, relabeled 17 outcomes from fill data.

Surviving pre-run artifacts checked:
- `/root/premium_trader_backup_20260406.sql`, `..._20260407_1650.sql`, `..._20260407_1759.sql`, `/opt/multi-agent-trader/backups/pre_tier_schema_20260409_195805.sql.gz` — **all April 6–9**, predating the funnel cutover (Apr 20) and every current trade. They contain none of the purged 87 labels.
- No pg_dump artifacts newer than April exist on the droplet.

### 2c. Plain statement

**The 87 pre-repair labels are unrecoverable.** Mitigating context: they were products of the phantom-outcome bug (70 of 87 sat on orders that never filled; PnL from limit prices) — the audit that motivated the purge established they were unfit for research. The loss is real but the lost data was worthless for training. **All 17 current labels are repair-run products, not original 17:00-labeler output** — they don't overlap Q1's indeterminate bucket (which is empty); they *are* Q1's population, and Q1 classified them directly. The process lesson stands regardless: rank 6 (revisioned outcomes) exists so this class of one-way door can't be walked through again.

---

## Question 3: Labeler fallback lower bound

### 3a. Current join logic (verified against working tree)

`services/outcome_labeler.py`, `_find_observation` — the join is:

```python
NameObservation.symbol == symbol
NameObservation.tier == 2
NameObservation.was_considered == True
NameObservation.timestamp <= trade_datetime + timedelta(days=1)   # midnight-UTC anchor + 1d
ORDER BY timestamp DESC LIMIT 1
```

**No lower bound of any kind.** `trade_datetime` is midnight UTC of the trade date, so the window is "any observation ever, up to 00:00 UTC the day after the trade" — which admits the trade day's later sweeps (18:0x UTC = 14:0x ET) and, when the symbol is absent that day, silently reaches back arbitrarily far.

### 3b. Proposed fallback bound

```python
window_start = trade.created_at - timedelta(days=1)
NameObservation.timestamp >= window_start
NameObservation.timestamp <= trade.created_at        # ≤ decision time, NOT trade_date+1d
ORDER BY timestamp DESC LIMIT 1
```

- Upper bound = the trade's actual `created_at` (decision moment), not a midnight-anchored +1d — this alone eliminates the wrong-sweep class.
- Lower bound = 24h before decision; wide enough for a morning trade to reach the prior day's final sweep, tight enough to exclude stale promotions.
- **When nothing falls in the window: `signal_profile=NULL`, `name_observation_id=NULL`, and `funnel_driven=NULL` (unknown) — not `False`.** "No surviving evidence" and "evidence of non-funnel origin" must be distinguishable; the learner's filter (`funnel_driven == True`) already excludes both, but dashboards and future audits need the distinction. Note: `funnel_driven` is currently `Boolean, default False` — allowing NULL is a nullable-column semantic change worth one line in the Block 1 migration (`models/trade_outcome.py`; the column is already nullable in Postgres, only the writer logic changes).

### 3c. Other callers needing the same bound

Grep-verified across `agents/ api/ services/ scripts/ core/ main.py tests/`: **no other code joins observations to trades.** The labeler's `_find_observation` is the only trade↔observation join. Two adjacent sites need awareness, not the same bound:

- `agents/tier2b_reasoning.py:328-336` — symbol lookup with `timestamp >= cycle_start`, `.limit(1)`, **no order_by** (nondeterministic if >1 row). Post-migration it must target the current sweep_id, not "any of today's rows."
- `agents/chat_agent.py:27-73,115` — the chat agent's SCHEMA_CONTEXT teaches the LLM to write free-form SQL against `name_observations` with plain time filters; after append-only, that prompt doc must describe sweep semantics or chat-generated analytics will double/triple-count.

---

## Question 4: Lead Agent model discrepancy

### 4a. Confirmed — the model changed mid-experiment, 2026-07-08

- Current config: `llm_model = "zai-org/GLM-5.2"`, `llm_base_url = "https://api.together.xyz/v1"` (`config/settings.py:23-26`).
- `git blame`: lines 23-26 written in commit **`4a92b26` (authored 2026-07-07 23:26 ET, deployed via PR #1 merge `a614995` on 2026-07-08)** — the audit-remediation commit. The commit message documents it ("lead agent LLM migrated from Anthropic claude-sonnet-4-6 to zai-org/GLM-5.2 on Together AI"); **no ADR was written**. README/architecture docs (ADR-017) still say Claude Sonnet — stale.
- Sleeve calls use the **same** shared `LLMService` instance (`agents/sleeve_orchestrator.py` calls `lead.llm_service.get_cycle_decision`), so every sleeve decision switched models at the same deploy. Per-sleeve attribution exists via `llm_usage_log.caller` (set per sleeve at orchestrator `:328`).

### 4b. Model IS recorded per cycle — distribution:

```sql
SELECT COALESCE(llm_model,'(null)') AS model, COUNT(*), MIN(timestamp)::date, MAX(timestamp)::date
FROM cycle_snapshots GROUP BY 1;
--        model       | count |   first    |    last
--  claude-sonnet-4-6 |   336 | 2026-04-07 | 2026-07-07
--  zai-org/GLM-5.2   |     9 | 2026-07-08 | 2026-07-10
--  (null)            |     3 | 2026-04-06 | 2026-04-07
```

Segment analysis is fully possible: every decision is attributable to its model. All 17 current labeled outcomes (trades Apr 10–Jun 22) are **Sonnet-era decisions**; GLM has made 9 cycles and no labeled trades yet.

### 4c. Handling recommendation

- **Flag as an uncontrolled variable, but a well-instrumented one.** Add to the experiment record: decisions before 2026-07-08 = claude-sonnet-4-6; after = zai-org/GLM-5.2. Day-180 evaluation should segment per-model (Sharpe/win-rate per model era) — with the caveat that the era boundary coincides with the outcome-integrity fixes, so model and data-quality effects are confounded across the boundary.
- **Bigger finding: `EXPERIMENT_CHARTER.md` is an unfilled template** — no experiment ID, start date, thresholds, or registered sleeves. The "Day-180 evaluation" has no registered baseline to be evaluated against. Recommend: register the charter now, backdated honestly (funnel cutover 2026-04-20 as start), with the model switch recorded as a protocol amendment.
- Per-decision model persistence: already adequate (`cycle_snapshots.llm_model`, `llm_usage_log.model/caller`). **No Block 1 addition needed** — with one exception: the conflict-resolver's ad-hoc client bypasses `llm_usage_log` model attribution; its verdict payload (Q5d) should carry the model string.

---

## Question 5: Block-scoping verification

### 5a. Freeze-at-decision write path

Both orchestration paths converge on one choke point:

- **Legacy path:** `lead_agent.py:182-193` (LLM decision → `_execute_action`) → `:1151-1176` (`worker.assigned_securities = [symbol]`, then `scan → evaluate → execute`) → worker `execute()` → `perf_logger.log_trade` (CSP `worker_csp.py:304-319`, CC `worker_cc.py:304-320`, Wheel `worker_wheel.py:474-489`).
- **Sleeve path:** `sleeve_orchestrator.py:123 → :137 _consolidate → :148 risk gate → :154 await self.lead._execute_action(action)` — identical hops from there.

**`services/logger_service.py:26` (`log_trade`) is the only place in the codebase that constructs a `Trade` row** (grep-verified) — entries, exits, and assignments from all three workers pass through it. The snapshot copy belongs there: for entry trade_types (`sell_to_open`/`buy_to_open`), select today's latest tier-2 observation for the symbol *in the same session* and copy `observation.id` + `analysis` onto the trade row. Workers don't know the observation (the orchestrator's action dict has `sleeve_id`/`estimated_edge` but that context is dropped before `worker.execute`), so a log_trade-internal lookup is strictly less plumbing than threading a kwarg through three workers' `scan/evaluate/execute`.

**Liveness:** in normal scheduling the observation written at :00 is alive at the :20 cycle and for ~100 minutes after — the copy is intra-cycle safe. Two real crossing risks: (i) a long multi-sleeve cycle (4+ sequential LLM tool loops, `sleeve_orchestrator.py:81-154`) bleeding past the next sweep hour (10:20 cycle still executing at 12:00 → its observations deleted mid-execution); (ii) manual sweep scripts (`scripts/run_tier2a.py`, `run_universe_sweep.py`) deleting rows at any time. Freeze-at-decision converts both from label-corruption bugs into a rare "snapshot lookup found nothing" (→ NULL, handled per 3b). Requires the Block-1 migration on `trades` (`name_observation_id`, `signal_snapshot`) as already sketched in RECON_STRUCTURED_DATA.md.

**Amendment discovered:** the same plumbing gap explains why `trade_outcomes.sleeve_id` is all-NULL (Q1a). The sleeve is known only in the orchestrator's action dict and is dropped at the same point. Cheapest fix in the same stroke: orchestrator sets `worker.current_sleeve_id = action["sleeve_id"]` right before `_execute_action` (same pattern as `assigned_securities`), and `log_trade` copies it onto the trade. Without this, the Day-180 **per-sleeve** evaluation has no data path at all — recommend folding into Block 1.

### 5b. Partial-fill handling scope

Verified two ways:

- Code: `broker.get_order()` returns `filled_qty` (`services/alpaca_broker.py:722`) and `filled_avg_price` on every order regardless of terminal status; `get_all_orders()` likewise (`:599`).
- Data: from the full raw order history captured during the July audit (166 orders, saved at audit time): **80 expired/canceled orders, zero with `filled_qty > 0`; no `partially_filled` status appears anywhere in the account's history.** Alpaca's paper matching engine appears to fill options all-or-none at this volume (1–4 contract orders).

Implication: the fields exist and are readable, so the reconciler fix ships as designed — but paper-mode partial fills are **untestable in practice** (zero historical occurrences to validate against). Mark reconciler-recorded partial fills as estimated (`notes` marker) per the request, and note there is **no backfill needed**: historical exposure to the lost-partial-fill bug is zero.

### 5c. sweep_id reader inventory

**The prior estimate of ~5 readers was wrong — there are 13 reader sites plus 4 delete-rewrite writer sites.** Full enumeration:

Writers to convert (delete removed, sweep_id stamped): `agents/tier2a_prefilter.py:334-344`, `agents/breadth_analyst.py:333-338`, `services/tier_writer.py:44-49` (+ its caller `scripts/run_universe_sweep.py`).

| # | Reader | Current filter | Needed semantics | Count-multiplication risk |
|---|---|---|---|---|
| 1 | `agents/tier2a_prefilter.py:110-118` | tier-1 today | latest tier-1 sweep | on rerun |
| 2 | `agents/tier2b_reasoning.py:114-120` | tier-2 today, by score | latest sweep | **yes** — would re-reason every sweep |
| 3 | `agents/tier2b_reasoning.py:329-335` | symbol, today, limit 1, no order | **current sweep** | arbitrary row |
| 4 | `agents/sleeve_orchestrator.py:228-234` | tier-2 today | latest sweep | **yes** — dup candidates to sleeves |
| 5 | `agents/lead_agent.py:1059-1066` (legacy) | tier-2 today, limit N | latest sweep | yes — top-N wasted on dups |
| 6 | `agents/research_analyst.py:148-155` | tier-2 today, limit 20 | latest sweep | yes |
| 7 | `services/outcome_labeler.py:437-444` | ≤ trade_day+1d, latest first | **as-of decision** (fallback only after Block 1) | wrong-row |
| 8 | `api/routes/dashboard.py:33-46,104-109` `/status` | all rows today, grouped | **latest-sweep counts** | **YES — displayed funnel counts ×3** |
| 9 | `api/routes/dashboard.py:49-60` | max(timestamp) per tier | fine as-is | no |
| 10 | `api/routes/dashboard.py:140-149` `/promotions` | day window, limit 50 | latest sweep of that day | yes |
| 11 | `api/routes/dashboard.py:191-197` `/signals` | 14–90d window | modeling choice; currently ≤1 row/sym/day | rates skew to multi-sweep survivors |
| 12 | `api/routes/dashboard.py:328-340` `/daily-stats` | per-day counts | per-day, deduped to latest sweep | **YES — daily chart ×3** |
| 13 | `api/routes/research.py:67-70,104-107,146-149,215-217` | today/window scans | latest-sweep counts / dedup | yes (`:67-70` flagged) |
| 14 | `scripts/research_inspect.py:67-74,141-145,242-253,266-273` | day windows, counts | same classes | yes for counts |
| 15 | `scripts/run_backtest_config.py:88-92` | tier-2 window, **no was_considered filter** (rejects intentional) | per-day dedup or per-sweep grouping | yes — backtest math assumes ≤1 row/sym/day |

Plus the chat agent's SQL prompt doc (3c above). Semantics split: **"as-of X"** is needed only by the labeler fallback (#7) and any future drill-down views; everything else wants "latest sweep" or "latest sweep per day." The clean design: `sweep_id` UUID + a small helper (`latest_sweep_id(tier, day)`) used by all count/list readers, keeping raw rows queryable for as-of research.

### 5d. Conflict-verdict persistence — confirmed shape and scope

Confirmed: `models/agent_action.py:37` — `payload = Column(JSON, nullable=True)` (`sa.JSON` in migration `p0q1r2s3t4u5:33`). **No migration needed.** Writer precedent: `sleeve_orchestrator._log_action` (`:628-646`).

Resolution flow verified — three modes, all data in scope as locals at `sleeve_orchestrator.py:506-537`:
1. **Deterministic ETF rule** — `_resolve_conflict_deterministic` `:31-54` (only rule: sector_rotation wins ETFs, `:50-51`)
2. **LLM judge** — `_resolve_conflict_via_llm` `:410-474`: Llama-3.3-70B (`:454`), max_tokens=50, one-liners from each claim's `reason`, answer string-matched `:462-467`
3. **Load-balance fallback** — `:526-530`, `min(position_count)`

In scope with zero new plumbing: symbol, claims (sleeve_id + full action incl. `estimated_edge`, contracts, dte), sleeve_infos (position_count), `all_signals[symbol]` (fired signals + asset type), winner/losers, resolution branch. Two trivial adjustments needed: `_resolve_conflict_via_llm` must return (or log internally) its raw `answer` string — currently discarded — and a two-line timing wrap for latency. The payload shape proposed above stands, with `losers: [...]` added.

### 5e. Effort revisions (honest numbers)

| Block | Was | Now | Why |
|---|---|---|---|
| Block 1 | ~1.5 days | **~2.5 days** | Freeze-at-decision needs the `trades` migration + log_trade lookup + labeler fallback bounds + NULL-funnel_driven semantics; reconciler fix is as scoped; verdict persistence needs the small resolver restructure; **+ the sleeve_id attribution amendment (5a)** which wasn't in the original scope but blocks the Day-180 per-sleeve evaluation |
| Block 2 | ~2 days | **~3 days** | 13 readers + 4 writers, not ~5 readers; the two dashboard count surfaces (×3 bug class) need a latest-sweep helper + tests; chat SCHEMA_CONTEXT update; backtest script dedup |
| Block 3 | ~1 day | **~1 day (holds)** | Shared-path envelope is as scoped; the GLM path is one parser |

### 5d. Conflict-verdict persistence shape

`agent_actions.payload` is a `json` column (verified via `\d agent_actions`) — a dict payload lands with **no migration**. The table also has `target_symbol`, `outcome`, `reason`, `score`, and `cycle_snapshot_id` columns that map naturally. Proposed shape:

```jsonc
// agent_actions row:
//   agent_name: "Sleeve-Orchestrator", action_type: "conflict_resolved",
//   target_symbol: <contested symbol>, outcome: <winning sleeve_id>,
//   cycle_snapshot_id: <current cycle>, payload:
{
  "contested_symbol": "NVDA",
  "resolution_mode": "llm_judged",        // "deterministic_etf" | "llm_judged" | "fallback_load_balance"
  "competitors": [
    {"sleeve_id": "event_driven",   "one_liner": "...", "score": 0.71},
    {"sleeve_id": "vol_reversion",  "one_liner": "...", "score": 0.64}
  ],
  "winner": "event_driven",
  "verdict_text": "<raw LLM answer>",     // null for deterministic/fallback modes
  "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",  // null for non-LLM modes
  "latency_ms": 850,
  "schema_version": 1
}
```

*(exact in-scope variables per resolution mode confirmed in agent trace below)*

### 5e. Effort revisions

*(final numbers after agent trace — below)*

---

## Question 6: Push back

**Pulling rank 7 forward: agreed, with one note.** The reasoning holds — the resolver exists for auditability and unpersisted verdicts defeat it. Cost is genuinely ~2h (no migration, all data in scope). The note: the resolver's raw LLM answer is currently discarded inside `_resolve_conflict_via_llm` (`:469-474` returns None on failure paths too), so persistence requires logging inside that method or widening its return — do it as part of the change, not as a follow-up, or failure-mode verdicts (the most interesting ones) won't be captured.

**Block plan is correctly ordered but under-scoped in two places** — see 5e. The material one is Block 2: half its real work is the *reader* migration (13 sites), and two dashboard surfaces will display ×3-inflated counts if the writers go append-only before the readers get latest-sweep semantics. **Writers and readers must land in the same deploy** — this is not a "migrate schema, fix readers later" change.

**Amendments recommended to Block 1** (both discovered during this recon):
1. **Sleeve attribution** (5a): `trade_outcomes.sleeve_id` is all-NULL because the sleeve context is dropped at the same plumbing point as the observation. Without it there is no per-sleeve Day-180 evaluation. One extra field through the same new path — cheapest now.
2. **`funnel_driven` NULL semantics** (3b): distinguish "no evidence" from "evidence of non-funnel" while touching the labeler anyway.

**Additional contamination mechanisms found (Q1's class, unasked-for):**
1. **Pseudo-replication:** the learner counts contracts, not decisions — 10 samples ≈ 7 decisions today (AMGN ×2, CRM ×3 share observations). At n=50 this silently overstates statistical power; MIN_SAMPLES should count distinct decision events (or distinct `name_observation_id`s). Small change in `signal_learner._load_data`; recommend adding to Block 3.
2. **Chat-agent SQL is a label-adjacent reader** whose prompt schema doc will silently mislead after Block 2 (3c) — update SCHEMA_CONTEXT in the same PR.
3. **The experiment charter is an unfilled template** (Q4c). Every evaluation-design question this recon touches (per-sleeve criteria, model segmentation, n=50 gate) currently has no registered baseline. Registering it — honestly backdated to the Apr 20 cutover, with the Jul 8 model switch and Jul 8 data repair recorded as protocol amendments — costs an hour and should happen before Turn 2 ships anything.
4. **Model/data-quality confound at the era boundary:** the GLM switch and the outcome-integrity fixes deployed in the same commit (`4a92b26`). Sonnet-era vs GLM-era performance comparisons are confounded with label quality unless the analysis conditions on post-fix labels only. Note this in the charter amendment.

**One thing that turned out better than the review assumed:** model attribution (Q4b) is already complete — `cycle_snapshots.llm_model` has been populated since April, and `llm_usage_log.caller` gives per-sleeve granularity. No Block 1 addition needed for it; the proposed "persist model identifier" item can be dropped except for the conflict-resolver payload's `model` field.

**Bottom line for approval:** the plan is sound; approve with Block 1 = 2.5 days including the two amendments, Block 2 = 3 days with writers+readers atomic, Block 3 unchanged plus the decisions-not-contracts learner fix. First learner training should exclude outcome ids 96–99, 103, 104 (the six wrong-sweep labels) and treat effective clean n as 4.
