# Recon: Frontend Alignment with the Remediated Architecture

Generated: 2026-07-12
Status: Recon only — no code changes. Companion to PR #2 (structured-data
remediation) and the 2026-07-08 outcome-integrity deploy.

Frontend today: 4 pages (`CommandCenterPage`, `HistoryPage`, `RulesPage`,
`ChatPage` under `dashboard/src/pages/`), API surface in
`dashboard/src/api.js`, Win95-styled components. The backend now emits
several structured artifacts the UI either renders as prose walls, renders
wrongly, or doesn't render at all.

---

## 1. Breaking / correctness items (ship with or immediately after PR #2)

### 1.1 `funnel_driven` is now three-state — the ✓ column and filter treat it as boolean
- `HistoryPage.jsx:233` renders `t.funnel_driven ? '✓' : ''` and `:152` filters `funnelOnly && !t.funnel_driven`.
- After PR #2 the labeler emits `True` (evidence), `False` (pre-cutover), and **`null` (no surviving evidence — unknown)**. Null currently renders identically to False, silently re-merging the two categories the backend just separated.
- **Fix:** three-state render — ✓ / blank / `?` (title: "post-cutover trade, no surviving observation evidence") — and the funnel-only filter should exclude null but the `?` must be visible in the ALL view. **Effort: XS.**

### 1.2 New trade status `partially_filled` hits the fallback capitalizer
- `api/routes/dashboard.py` display_outcome else-branch renders it as literal `Partially_filled`.
- **Fix:** map to `Partial Fill` (server-side, one line in the display_outcome chain) + client badge styling. Note the row's `quantity` is rewritten to the filled qty and notes carry the "(estimated — paper mode)" marker worth surfacing in the row tooltip. **Effort: XS.**

### 1.3 Learning progress will drop 10 → 4 — label it or field questions
- The Command Center "Learning: n/50" line (`CommandCenterPage.jsx`, `/status.learning_progress`) will show **4/50** after tonight's labeler run (decisions, not contracts; contaminated labels excluded).
- **Fix:** relabel to "Learning: 4/50 clean decisions" with a tooltip explaining the July recon; otherwise this reads as a regression. Consider also showing `funnel_driven=null` count as "n unknowns". **Effort: XS.**

### 1.4 Funnel widget semantics changed from "today" to "latest sweep"
- `/status.funnel` counts are now the latest sweep's counts (correct, non-multiplying), but the label "Universe N → T2 M" doesn't say *which* sweep. With 3 sweeps/day the number now changes intraday in a way that's confusing without a timestamp.
- **Fix:** append the sweep time (already available via `last_tier2_sweep`): "Universe 4,102 → T2 38 (as of 14:04)". **Effort: XS.**

## 2. New data the frontend doesn't render at all (the real payoff)

### 2.1 Judgment envelopes — replace the prose wall
- `cycle_snapshots.full_context.envelope` (legacy path) and `.sleeve_envelopes` (orchestrator path, keyed by sleeve) now carry `{verdict, one_liner, factors[{signal, direction, weight}], confidence}`. **Verified: the `/dashboard/cycles` endpoint does NOT return `full_context`** — it serializes only summary/reasoning/cost fields. Two-line API addition: `"envelope": (c.full_context or {}).get("envelope")` and `"sleeve_envelopes": (c.full_context or {}).get("sleeve_envelopes")`.
- `HistoryPage.jsx:424` renders `stripFences(c.reasoning)` — a wall of text per cycle.
- **Build:** per-cycle card header = verdict chip + one_liner + confidence bar; factor chips (signal name, direction arrow, weight-scaled opacity); full prose behind the existing expander. Per-sleeve envelope grid for orchestrator cycles instead of scrolling the `=== sleeve ===` blob. Degraded envelopes (`degraded: true`) fall back to today's rendering. **Effort: M (1 day incl. API field).**

### 2.2 Sleeve attribution — the per-sleeve view the charter requires
- `trades.sleeve_id` and `trade_outcomes.sleeve_id` populate from the next entry trade onward; `/dashboard/trades` already returns `sleeve_id`.
- Nothing renders it. The experiment charter's Day-90/180 checkpoints need per-sleeve win rate/PnL, and the History page can't even filter by sleeve.
- **Build:** sleeve column + filter chips on HistoryPage; a "Sleeves" panel (per-sleeve: trades, win rate, PnL, learning contribution) — either on Command Center or a new tab. Data is one GROUP BY on existing endpoints; propose extending `/dashboard/trades` summary with a `by_sleeve` map rather than a new endpoint. **Effort: M.**

### 2.3 Conflict-resolution verdicts — new audit surface
- `agent_actions` rows with `action_type='conflict_resolved'`: contested symbol, competitors with one-liners + edges, winner/losers, resolution_mode (deterministic / llm_judged / fallback), verdict text, model, latency.
- No endpoint exposes agent_actions to the dashboard today.
- **Build:** `GET /api/dashboard/conflicts?days=7` (thin query) + a small Command Center feed ("XLV: event_driven beat vol_reversion — llm_judged"). Low volume (only fires on collisions), high audit value. **Effort: S.**

### 2.4 Fill quality — slippage becomes visible
- `trades.fill_price` + `filled_at` now recorded; `premium` still holds the submitted limit. `fill_price − premium` is per-trade slippage; entry-order miss rate (~55% in the audit) is the funnel's biggest throughput drag.
- **Build:** History row tooltip: limit vs fill vs slippage; a small "fill rate (30d)" stat on Command Center (filled STO count ÷ submitted STO count from existing `/trades` data). This directly instruments the n=50 timeline lever. **Effort: S.**

## 3. Consistency notes (no action strictly required)

- **Daily-stats promotion chart:** values stay continuous — legacy days already held exactly one surviving sweep, and the new `sweep_dedup_filter` keeps one sweep/day going forward. No discontinuity to annotate.
- **Tier2b reasoning:** API now prefers the dedicated column with JSONB fallback; response shape unchanged (`promotions[].reasoning`). No frontend change.
- **Reconciliation panel** (shipped 2026-07-08) already renders `ok / discrepancies / drift`; with conflict + fill data landing, consider consolidating these into one "Integrity" window — natural future home for Integrity Sentinel output (BACKLOG item).
- **ChatPage:** schema doc updated server-side; no UI change, but chat answers about promotions will now mention sweep semantics — no action.

## 4. Suggested build order

| # | Item | Effort | Why first |
|---|------|--------|-----------|
| 1 | §1.1–1.4 correctness batch | ~half day total | Ships alongside PR #2 so the UI never displays wrong/confusing states |
| 2 | §2.1 envelope rendering | M | Highest visible payoff of Block 3; makes every future cycle legible |
| 3 | §2.2 sleeve views | M | Charter Day-90 checkpoint (2026-07-19) wants per-sleeve numbers |
| 4 | §2.4 fill quality | S | Instruments the biggest funnel-throughput lever |
| 5 | §2.3 conflicts feed | S | Completes the auditability story |

Total: ~3 days of frontend work, no new backend tables required; two small API additions (envelope fields on `/cycles`, conflicts endpoint, optional `by_sleeve` summary).
