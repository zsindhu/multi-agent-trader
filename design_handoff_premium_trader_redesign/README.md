# Handoff: Premium Trader Dashboard Redesign (Win95 × Bloomberg)

## Overview

Full redesign of the Premium Trader dashboard (`dashboard/src/` — React + Vite +
react-router). New information architecture, new screens, and reusable patterns
aligned with the remediated backend (PR #2 structured-data changes and the
2026-07-08 outcome-integrity deploy, per `RECON_FRONTEND_ARCHITECTURE_ALIGNMENT.md`).

The design went through 5 iterations. **Implement the FINAL versions only:**

| Screen | Final design | Location in `Command Center Options.dc.html` |
|---|---|---|
| Command Center (home) | **5a** | `<div class="dv-opt" id="5a">` |
| Pipeline | **3a** | `id="3a"` |
| Trades & Learning | **3b** | `id="3b"` |
| Agents (admin-only) | **3c** | `id="3c"` |
| Chat | **3d** | `id="3d"` |
| Judgment envelope card (pattern) | **4a** | `id="4a"` |
| 3-state learning progress (pattern) | **4b** — already folded into 5a | `id="4b"` |
| Integrity window (pattern) | **4c** — already folded into 5a | `id="4c"` |
| Digestible reflection (pattern) | **4d** | `id="4d"` |

Ignore options 1a/1b/1c/2a — superseded explorations kept for history.

## About the Design Files

The bundled `Command Center Options.dc.html` is a **design reference created in
HTML** — a prototype showing intended look and behavior, NOT production code.
Recreate these designs in the existing React dashboard (`dashboard/src/`),
reusing its patterns (`W95Window.jsx`, `win95.css`, `api.js` fetch hooks,
react-router pages). All markup uses inline styles; translate to the existing
`win95.css` class system where classes exist, extend it where they don't.

## Fidelity

**High-fidelity.** Colors, borders, font sizes, and spacing are final and match
the existing Win95 × Bloomberg system. Recreate pixel-perfectly. All data shown
is invented sample data — wire to the real API.

## Design Tokens (shared with existing `win95.css`)

- Chrome gray `#c0c0c0` · desk gray `#d4d0c8` · white field `#ffffff`
- Title-bar navy `#000080` · secondary navy `#0000b0` · muted navy-text `#a0a0ff` / `#c0c0ff`
- Gain green `#008000` · loss red `#ff0000` · warn olive `#808000` · muted `#808080`
- Terminal panels: bg `#000`, text `#00ff00`/`#c0c0c0`, agent-name cyan `#00c0c0`, warn `#ffff00`, dim `#606060`
- Admin nav bar (Agents screen only): `#400000` with `#ff8080` session text
- Borders: raised = `2px outset #dfdfdf`, sunken = `2px inset #dfdfdf`, thin table borders `1px solid #c0c0c0`
- Fonts: UI = Tahoma 9–12px; data = 'Cascadia Mono', monospace 10–11px
- Sleeve badge backgrounds: EVT `#e8e8ff`, VOL `#e8ffe8`, SEC `#fff0e0`, YLD `#ffffe0`; badge = 9px Tahoma uppercase, `1px solid #808080`
- No border radius anywhere. No shadows except desktop-metaphor windows (unused in finals).

## Global Chrome (all screens)

- **Top nav bar** (replaces current top-tab strip): navy `#000080` bar, brand
  "PREMIUM TRADER" bold 12px white; tabs = 11px; active tab looks like a raised
  button (`2px outset`, `#c0c0c0` bg, bold black); inactive = flat `#c0c0ff`;
  "Agents 🔒" tab is `#6060a0`, `white-space:nowrap`, admin-gated.
  Right side: monospace 10px `#a0a0ff` clock, e.g. `FRI JUL 11 · 13:42 ET · MARKET OPEN`.
- **Window panel pattern** (existing `W95Window`): outer `2px outset` on
  `#c0c0c0`, navy title bar (bold 12px white, 2px 4px padding, may carry a
  right-aligned 10px status like `SYNCED 13:41` in `#80ff80`), body inset
  `2px inset` with 2px margin, white or black bg.
- **Tables**: header cells navy bg / white Tahoma 11px / `1px solid #808080`;
  body monospace 11px, `1px solid #c0c0c0` cells, zebra `#fff` / `#f0f0f0`;
  highlighted row `#fff8e0`; P&L cells bold green/red.
- **Bar meters**: track `1px inset` on `#d4d0c8`, fill solid navy (capital),
  green/red (P&L), height 8–12px.

## Screens

### 1. Command Center — final design **5a**

Answers: *"Am I making money and is anything wrong?"*

Layout: nav bar → pipeline-spine strip → body grid `1fr 300px`, 4px gaps.

- **Pipeline spine strip** (`#d4d0c8`, bottom `2px outset`): 6 stage boxes
  (`2px outset`, min-width 96px) — Universe 6,350 / Tier 1 4,285 / Tier 2a 87 /
  Tier 2b 42 / Lead Agent 9 / Trades 2 — each with 9px uppercase label, 16px
  bold mono count, 9px sub-label; `▶` separators. Lead Agent box bg `#e8e8ff`
  navy text; Trades box navy bg white text. After last box: 9px note
  **"as of 15:15 sweep"** (§1.4 of the recon — funnel counts are per-sweep, must
  show sweep time, sourced from `last_tier2_sweep`). Right side: REGIME box
  (white inset, olive bold value) then LLM SPEND TODAY box (black inset, green
  terminal text `$0.62`).
- **Left column**: (a) grid `1fr 300px`: Equity window (title shows
  `$512,847 +2.6% · today +$438`, +values in `#80ff80`; 150px white chart area,
  navy line + `#e8e8ff` area fill) beside "Sleeves — P&L" (4 rows: 86px 10px
  Tahoma name, P&L bar, 56px bold value; footer row "Total premium MTD").
  (b) 4 sleeve cards (equal grid): title bar name + 3-letter tag; rows P&L /
  Positions "3 / 5" / Capital used "$91K / $125K"; navy capital bar.
  (c) Positions table, flex-fill: SYMBOL, SLEEVE badge, TYPE, STRIKE, EXP,
  DTE, ENTRY, P&L, ALPACA (MATCH green / PENDING olive). Title:
  "Active Positions (8) — vs Alpaca: 8/8 matched" + "SYNCED 13:41".
- **Right rail (300px)**: (a) **Agent Activity — Live**, flex-fill black
  terminal: rows `HH:MM [AGENT] message`, 10px mono, 1.6 line-height; colors:
  time `#606060`, agent `#00c0c0`, fills/recon-ok `#00ff00`, risk-pass
  `#00c000`, warnings `#ffff00`, trades white, routine `#c0c0c0`.
  (b) **Learning Progress** (3-state, recon §1.3): "Clean decisions **4 / 50**";
  50-segment bar (segments flex:1, 1px gaps, in a `2px inset` track): navy =
  clean(4), `#c0c000` = unknown evidence(3), rest empty; legend underneath;
  note "Jul 12 relabel: decisions, not contracts. Activates at 50 clean."
  `funnel_driven=null` counts feed "unknown".
  (c) **Integrity window** (consolidation, recon §3): title + right-aligned
  "ALL CHECKS PASS" `#80ff80`; rows Broker recon `8/8 · drift $65↓`, Entry fill
  rate 30d `45% (18/40)` (olive — computed filled÷submitted STO), Avg slippage
  `-$0.03/ct` (fill_price − premium), Conflicts 7d `2 resolved`, Errors today,
  Last cycle `15:31 ($0.0790)`; footer link "▶ Full audit on Agents screen".

### 2. Pipeline — design **3a**

Answers: *"What is the system looking at and why?"*

- **Expanded spine**: same 6 stages, each box flex:1 with a 4th line (divider +
  9px mono): "refreshed 06:30" / "swept 06:42 · 8m 12s" / "ran 13:02 · 3x daily" /
  "ran 13:05 · $0.11" / "cycle 13:31 · $0.08" / "both filled".
- **Promotions table** (left, fill): # / SYMBOL / SCORE (4dp) / FIRED / TOP
  SIGNALS (10px) / SLEEVE ROUTE badge / AMP ("1.5x" when amplified). Title
  notes "CLICK ROW TO EXPAND". **Expanded row** (bg `#e8e8ff`, spans all cols):
  4-col grid of signal chips — `name: raw z=… FIRED` — fired = `#e8ffe8` bg
  `1px solid #008000`, unfired = white/`#d0d0d0`; below, "Tier 2b reasoning
  (Llama 3.3):" + prose. (API: `promotions[].reasoning`, shape unchanged.)
- **Right rail (330px)**: Signal Fire Rates 14d (8 label+bar+% rows) ·
  Scan Schedule (times with DONE green / next pending gray; "Lead cycles today
  4 of 6") · Near Misses (symbol + one-line reject reason, e.g. "1 rule fired
  (needs 2)", "missed 0.80 threshold by 0.01").

### 3. Trades & Learning — design **3b**

Answers: *"Is it getting better?"*

- **Learning banner** (below nav, `#d4d0c8`): wide progress box (labeled bar +
  "22 wins · 9 losses · activates at 50" note) + three white inset stat boxes:
  Win rate 71% (green 18px) / Realized P&L +$8,412 / Avg win/loss $486 / $312.
  ⚠ Update numbers to the 3-state model when implementing (4/50 clean).
- **Trade History** (left, fill): filter toolbar (Sleeve/Outcome dropdowns,
  symbol text filter, Clear) then table: CLOSED / SYMBOL / SLEEVE badge / TYPE /
  STRIKE / P&L / LABEL (WIN green, LOSS red bold) / EXIT REASON (10px gray:
  "expired worthless", "50% profit target", "stop — breached strike",
  "assigned — to wheel", "rolled up+out").
  **Add per recon §1.1:** FUNNEL column — ✓ (true) / blank (false) / `?` (null,
  title "post-cutover trade, no surviving observation evidence"); funnel-only
  filter excludes null but `?` stays visible in ALL. **Per §1.2:** status
  `partially_filled` → "Partial Fill" badge; tooltip carries the
  "(estimated — paper mode)" note. **Per §2.4:** row tooltip limit vs fill vs
  slippage.
- **Right rail (330px)**: Sleeve Scorecard (compact table: SLEEVE/TRADES/WIN%/
  P&L — `by_sleeve` summary from §2.2) · **Alpaca Reconciliation** panel:
  rows (Last sync, Positions matched 8/8, Broker realized P&L, DB labeled P&L,
  Drift olive) + discrepancy card (`1px solid #808000`, `#fffff0` bg): bold
  olive headline "⚠ DISCREPANCY — COIN CSP $240", explanation, [Force re-sync]
  button; footer "Sync history (7d): 96.4% clean · 3 auto-patched · 0 manual" ·
  Daily P&L 30d: mini bar chart, 80px, bars from center line, green up / red down.

### 4. Agents (admin-only) — design **3c**

Answers: *"Is the machinery honest?"* Route must be auth-gated.

- Nav bar variant: **`#400000`** bg, inactive tabs `#c0a0a0`, right text
  `ADMIN SESSION · 13:42 ET` in `#ff8080`.
- **Integrity strip**: 5 white inset stat boxes — DB WRITES TODAY 14,208 /
  OVERWRITES "2 flagged" (olive) / READ COST TODAY $0.41 / INTEGRITY CHECK
  "PASS 05:00" (green) / GHOST TRADES 0 (green).
- **2×2 grid**: (a) **DB Write Audit** — AGENT / TABLE / INS / UPD / FLAG;
  flagged rows bg `#fffff0`, FLAG olive bold ("OVERWRITE", "DUP WRITE").
  (b) **Overwrite Detection** — warning cards (olive border, `#fffff0`):
  bold headline `⚠ table — SYMBOL HH:MM`, Tahoma explanation, [View diff]
  [Restore prior] buttons; below, green ✓ lines for clean tables.
  (c) **Per-Agent Cost** — label+bar+cost+calls rows, bars navy→teal→gray by
  rank; footer "MTD $41.20 of $150 budget (27%) · projection $118 ✓".
  (d) **Agent Message Bus** — black terminal, rows
  `HH:MM from→to message` (from cyan, arrow dim, to `#c000c0`).
- **Conflicts (recon §2.3)** live here in full: `action_type='conflict_resolved'`
  rows via new `GET /api/dashboard/conflicts?days=7` — contested symbol,
  competitors + one-liners + edges, winner, resolution_mode badge
  (DETERMINISTIC gray / LLM_JUDGED `#e8e8ff` / FALLBACK), verdict text.
  Add as a 5th panel or tab within this screen.

### 5. Chat — design **3d**

- **Chat window** (left, fill): title "💬 Chat Agent — session #a3f2" +
  "AVG RESPONSE 2.1s" green. User bubbles right-aligned, max 70%, `#e8e8ff`,
  `1px solid #808080`, 9px meta "YOU · 13:40". Agent replies max 85%: first a
  **tool-call block** (`#f0f0f0`, `1px solid #c0c0c0`, 10px mono):
  `▶ query_trades(sleeve=…, days=7) 184ms` — fast latencies green, LLM
  latency olive, "· cached" marker when applicable; then the answer bubble
  (white, meta "AGENT · 13:40 · 2.2s · $0.0041", key figures bold).
  Input row: inset text field + raised Send button.
- **Right rail (330px)**: Latency Budget (bars: DB queries 355ms, Embeddings
  120ms, Claude gen 1,840ms, Render 12ms; note "DB reads now cached (5-min
  TTL) — p50 2.1s, was 6.8s") · Agent Can See (✓ list + "× cannot place or
  modify orders" gray) · Suggested Queries (stack of raised buttons, 10px).

## Reusable Patterns

### Judgment envelope card (design 4a — recon §2.1, highest payoff)

Renders `{verdict, one_liner, factors[{signal,direction,weight}], confidence}`
from `cycle_snapshots.full_context.envelope` / `.sleeve_envelopes` (needs the
two-line API addition on `/dashboard/cycles`). Replaces every prose wall:
cycle history (HistoryPage:424), Tier 2b reasoning, journal.

- **Single**: header row = verdict chip (Tahoma 10px bold white on green
  OPEN / olive HOLD / gray PASS, `1px solid` darker) + one-liner 11px;
  confidence row = 64px right-aligned label + bar (green fill = confidence) +
  bold mono value; factor chips row (wrap, 3px gap): 10px mono
  `signal ▲|▼ weight`, supporting = green-tinted (`#e8ffe8`/`1px solid
  #008000`, fading with weight), opposing = red-tinted `#fff0f0`; footer link
  "▶ Show full reasoning (612 words)" → existing expander.
- **Per-sleeve grid** (orchestrator cycles): 2-col grid of mini-cards —
  verdict chip + sleeve name + confidence, one-liner below. Replaces the
  `=== sleeve ===` scroll blob.
- **Degraded** (`degraded: true`): gray title bar + "ENVELOPE DEGRADED";
  "⚠ Structured envelope failed validation — showing raw reasoning." + clamped
  raw text + Expand. This is the fallback = today's rendering.

### Digestible reflection (design 4d)

Reflection/journal template: **Three takeaways** (numbered 1/2/3, number
colored green/olive/red by valence, bold lead phrase + one sentence) →
**Changed since yesterday** (mono diff list: `+` added, `~` changed) →
**Watching tomorrow** (one Tahoma line) → "▶ Full reflection (438 words)".
Requires the reflection prompt to emit this structure alongside prose.

## Interactions & Behavior

- Nav: react-router tabs; Agents route admin-gated (hidden or lock-redirect).
- Promotions row click toggles expanded signal panel (one open at a time).
- Trade history filters combine (AND); funnel-only excludes `funnel_driven=null`.
- Envelope/reflection expanders reuse existing HistoryPage expander behavior.
- Agent Activity + Message Bus: poll (existing dashboard interval); newest on
  top; auto-scroll pinned to top unless user has scrolled.
- Force re-sync button → existing reconciliation endpoint; disable + show
  timestamp while running.
- Chat: tool-call block streams before the answer (render as tools resolve).
- Hover states: raised buttons depress (`outset`→`inset`); table rows highlight
  `#e8e8ff`. No transitions/animations — instant state changes fit the Win95 idiom.
- Responsive: desktop-first. Below ~900px stack right rails beneath main
  content; pipeline spine horizontally scrollable; tables horizontally
  scrollable in place.

## State & Data

Existing endpoints: `/status` (equity, funnel + `last_tier2_sweep`,
learning_progress, llm cost), `/dashboard/trades` (+`sleeve_id`, `fill_price`,
`filled_at`, `funnel_driven` 3-state), `/dashboard/cycles`, promotions,
reconciliation. New/extended per recon: envelope fields on `/cycles`,
`GET /api/dashboard/conflicts?days=7`, optional `by_sleeve` trades summary.

## Assets

None — no images or icon fonts. Glyphs are Unicode text (▶ ▲ ▼ ⚠ ✓ 🔒 💬).

## Files

- `Command Center Options.dc.html` — all design iterations; finals are ids
  `5a, 3a, 3b, 3c, 3d` and patterns `4a, 4d` (search for `id="5a"` etc.)
- `RECON_FRONTEND_ARCHITECTURE_ALIGNMENT.md` — backend recon this design
  implements; build order suggestion in its §4
