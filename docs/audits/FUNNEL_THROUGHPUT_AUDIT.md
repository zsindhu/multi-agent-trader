# Funnel Throughput Audit — Last 60 Days

> **Status as of 2026-10-21 (deployed f51c4c5):** the fill-rate cause (mid-priced limit orders
> expiring) was addressed by ea94bb1 (near-touch pricing + poll-and-chase, `services/order_chaser.py`).
> Still **open**: the ~0.1% LLM decision-rate bottleneck (policy), DAY-only time-in-force,
> unpersisted risk-gate rejection reasons, dead config keys, and the missing `regime_confidence`
> writer. Tracked in BACKLOG.md.

Generated: 2026-07-13 · Recon only, read-only queries, nothing committed
Window: 2026-05-14 → 2026-07-13 (60 days, ~42 trading days)

## The funnel, with real numbers

```
Tier 1 universe swept ............ ~4,380 distinct names/day (stable all 60d)
  └─ 9.0% promoted
Tier 2a promotions ............... 23,580 day-symbol promotions (≈393 distinct/day)
  └─ config filters (per sleeve, replicated over the actual 60d data)
Sleeve-eligible candidates/day ... event_driven ~20 · vol_reversion ~186
                                   yield_farming ~43 · sector_rotation ~1 (0 on 36/60 days)
  └─ top 15 per sleeve per cycle presented to the LLM (cap confirmed at
     sleeve_orchestrator.py:320 — the old "10 of 50" flag was the legacy tool path)
LLM exposure ..................... ≈135–180 candidate-slots/day across 3 cycles × 3 live sleeves
  └─ 0.1% become open decisions            ◄◄◄ THE CHOKE — 3 orders of magnitude
Open actions decided ............. 15 in 60 days (0.25/day)   [close 59 · hold 101 · no_action 145]
  └─ 73%
Entry orders submitted ........... 11 (all CSP; 4 decisions lost in worker evaluate/execute — not persisted why)
  └─ 45% fill
Orders filled .................... 5  (6 day-limit orders expired unfilled)
  └─ 100% — zero leak
Labeled outcomes ................. 5
  └─ contracts ≠ decisions
Clean labeled DECISIONS .......... 3  (CRM×3 contracts = one decision, XLV, XLC)
```

**Cycle reliability underneath:** 120 cycles ran (~93% of the expected ~129). 82 of 120 (68%) decided zero actions. Of the zero-action cycles: 43 completed and chose inaction with reasoning; 10 were Anthropic-API-error safe-mode no-ops (June 19–23); the rest show no terminal json block — truncation losses. **Truncation is NOT GLM-new:** Sonnet hit the 4096 cap 189 times in 1,681 calls (11%) during its era; GLM made it catastrophic (11/12 sleeve-finals lost on Jul 13, fixed in PR #5). Truncation amplified the drought; it cannot explain it.

## Ranked: where throughput actually dies

| # | Stage | Survival | 60d impact |
|---|-------|----------|------------|
| 1 | **LLM decision layer** (eligible → open decided) | **~0.1%** | The binding constraint by ~3 orders of magnitude. Everything else is rounding error against this. |
| 2 | Decision-layer *losses* (truncation + API errors) | ~10–30% of cycles compromised | 12 GLM sleeve-finals + ~189 Sonnet cap-hits + 10 safe-mode cycles. Real, now largely fixed (PR #5) — but even perfect delivery of observed decisions ≈ 20 opens/60d. |
| 3 | Fill rate (submitted → filled) | 45% (5/11; whole-life 17/38 = 45% — earlier audit confirmed) | Halves whatever survives #1. Day-limit orders at scored price; the 6 expirations skew to small premiums (XLV $0.69–0.89 expired 5/6; CRM $2.90–4.51 filled 3/3). Distance-from-mid at submission is **not reconstructible** — quotes weren't persisted. TIF is hardcoded `day` in all three workers. |
| 4 | Decided → submitted | 73% (11/15) | 4 decisions evaporated in worker evaluate/execute; no persisted reason (observability gap — silent drops). |
| 5 | Risk gate | ~100% pass | 1 persisted rejection in 60 days. **The gate is not the killer.** (Per-rejection reasons only ever went to container logs — unrecoverable, another observability gap.) |
| 6 | Post-fill pipeline | 100% | 5/5 filled → labeled. The remediation works; nothing leaks after a fill. |

## What the agents say when they complete and still do nothing (Q7)

Clustered from completed zero-action cycles across both model eras, in their own words:

1. **Earnings blackout, dominant in June–July** — "Q2 earnings wave blocks all quality large-caps through July 31 … Patience is the trade until the post-earnings window opens Aug 4+." The event_driven sleeve *requires* earnings proximity while the prompt's hard rule forbids selling into announcements ≤7d — it lives in a narrow 8–14-day keyhole and frequently disqualifies its entire top-15 one name at a time ("CNS (earnings 3 days — DISQUALIFIED), CE (3 days — DISQUALIFIED)…").
2. **Mandate/quality bars above what the funnel delivers** — "BABA is the sole earnings-clear candidate but fails the 'sleep well' mandate … only 2 signals (below 3+ threshold)." Sleeves demand 3+ fired signals; tier2a promotes at 2.
3. **Regime caution** — Hormuz re-escalation, VIX narratives; risk-off posturing produced watchlists, not trades.
4. **Sonnet-era displacement behavior** — many completed cycles spent their final tokens writing playbook entries and "forward watchlists" instead of actions ("### 📝 PLAYBOOK ENTRY TO ADD" as the cycle's terminal act).
5. **Contaminated feedback loop (period-specific):** decision prompts in this window cited the phantom-era stats — "30-day: 88% win rate (44W/6L), but total PnL -$1,956" — i.e., sleeves were reasoning from performance numbers we later proved fabricated.

## Structural findings (Q8–Q10)

- **Tier 2a rejection mix (60d):** below_min_signals 124,354 · insufficient_liquidity 64,076 · then per-rule near-misses (volume 16,305, correlation 11,218, iv_rank 10,360, range 10,297, gap 8,798, earnings 4,446). The 2-of-11 gate does most of the killing; that's design, and it still passes ~393 names/day — the top of the funnel is NOT the problem.
- **sector_rotation is unsatisfiable in practice:** 11-symbol SPDR whitelist ∩ 2+ fired change-detection signals ≈ 1 candidate/day, zero on 36/60 days. "No candidates for this sleeve" in virtually every cycle is the sleeve working as specified and starving.
- **Dead config keys:** `event_driven.exclude_post_earnings_days` and `yield_farming.max_iv_rank` are declared in YAML but never read by `_filter_promotions_for_sleeve` — silently ignored. `vol_reversion.min_iv_rank: 70` is implemented as a crude proxy (`|iv_delta| ≥ 21`).
- **regime_confidence is a dead field:** neither snapshot writer passes it (`lead_agent.py:1351`, `sleeve_orchestrator.py:668` omit it), nothing in the lead prompt reads it, yet the chat agent's schema doc advertises it — chat SQL can reference a column that has been NULL on all 352 cycles.

## The projection you asked for, plainly

Observed rates, 60 days: **15 open decisions → 11 orders → 5 filled contracts → 3 clean labeled decisions.**

Extrapolated to the charter's Day-180 horizon (Oct 17, ~97 calendar days remaining):

- Filled entry trades: ~5 per 60d → **~8 more fills, ~25 total contracts over the full 180 days**
- Clean labeled decisions: 3 per 60d → **~5 more, on top of the current 4 → roughly 9–10 by Day 180**

**Against the 50-decision activation threshold: the system as currently configured will reach ~20% of it.** Even a generous stack-up of every fix in flight — truncation recovery (PR #5, call it +30–50% decisions delivered), fill-rate work (45%→70%), zero worker drops — multiplies to maybe 2.5–3× observed throughput: **~25–30 clean decisions by Day 180. Still materially below 50.**

The honest conclusion: the charter's falsification condition — *"funnel throughput cannot produce 50 clean labeled decisions even after remediation"* — is on track to be met. The constraint is not data, not the mechanical funnel, not the risk gate, and only partially execution: **it is that the decision layer converts ~0.1% of what it sees, held there by prompt-level hard rules (earnings blackouts, 3+ signal thresholds, "sleep well" mandates) interacting with sleeve configs, plus a season (Q2 earnings) that the dominant sleeve design is allergic to.** A system this conservative may be *correctly* conservative per its rules — but the rules and the 50-decision experiment are mutually incompatible on a 180-day clock. Closing that gap requires changing decision policy or the threshold, not more integrity fixes.

Per instruction, no fixes proposed here.
