# Recon: Envelope Degradation — Root Cause

Generated: 2026-07-13 · Status: root cause confirmed; fix implemented + live-verified same day (see PR)
Scope: 11 of 12 sleeve envelopes rendering DEGRADED (cycles 349–352, 2026-07-13)

## Verdict up front

**The parser is fine and the envelope schema is fine. The completions are being truncated by `llm_max_tokens = 4096` before the json block is ever emitted.** GLM-5.2 is a reasoning model: its *hidden* thinking tokens and the visible content share the same 4096 completion budget per call. Sonnet-4-6 had no hidden reasoning, so 4096 was always enough; for GLM it frequently isn't, and `services/llm_service.py` never checks `finish_reason`. Both of your priors are partially refuted: it isn't nested-structure unreliability (the one complete output parsed a fully nested envelope perfectly) and it isn't parser strictness (the parser never received any JSON to reject).

## Evidence

### 1. Raw text diff (degraded vs successful)

All texts pulled from `cycle_snapshots.full_context->sleeve_envelopes[*].full_text` and replayed through the **actual** `parse_envelope`/`_parse_decision` code locally:

| Cycle · sleeve | full_text | json blocks | actions | envelope |
|---|---|---|---|---|
| 349 event_driven | 687 chars, **ends mid-word** ("…CE (earnings 3 days — DISQUALIFIED), AIR") | 0 | 0 | degraded |
| 349 vol_reversion | 130 chars, ends mid-sentence ("…pull fundamentals on CRNX which I haven't yet") | 0 | 0 | degraded |
| 351 yield_farming | 5,914 chars, ends mid-sentence ("…collateral ~$9,") — **zero opening fences** | 0 | 0 | degraded |
| **350 yield_farming** | 7,930 chars, ends with a **complete fenced block**: `{"actions": [...], "envelope": {verdict, one_liner, 5 factors, confidence 0.72}}` | 1 | 1 | **parsed** |
| 7 others (349 yield; 350–352 event+vol; 352 yield) | **length 0 — completely empty** | 0 | 0 | degraded |

Structural difference: nothing about JSON shape differs — the degraded texts simply **stop before any JSON exists**. Three subtypes, all one cause: (a) prose cut mid-sentence pre-fence, (b) prose cut inside the trade analysis long before the fence, (c) **empty content** — the entire 4096 budget consumed by hidden reasoning, so `message.content` came back empty/None (`final_text = msg.content or ""`).

### 2. Failure mode: NOT FINDING, never rejecting

`parse_envelope()` found **zero** json blocks in every degraded case (replayed locally against the shipped code). No Pydantic `ValidationError` occurred anywhere. There is no partial envelope to salvage — the fix class is "make the model finish," not "loosen the parser."

### 3. The smoking gun: token accounting

```sql
SELECT tokens_out, COUNT(*) FROM llm_usage_log
WHERE timestamp >= '2026-07-12' GROUP BY tokens_out ORDER BY COUNT(*) DESC;
--  tokens_out | count
--        4096 |    11      ← exactly at the cap, 11 times
--  (everything else appears once)
```

Eleven completions since Jul 12 hit **exactly 4096 output tokens** — the `finish_reason='length'` fingerprint. The single successful envelope (cycle 350 yield_farming) came from the only final turn that finished under the cap: **4,028 tokens at 16:24:37**. A 130-char visible text billed as a 4096-token completion means ~3,950 tokens of invisible GLM reasoning.

The code never inspects `finish_reason` (grep: zero occurrences in `llm_service.py`), so a truncated final turn is treated as a normal answer.

### 4. Actions fail in lockstep with envelopes — same block, same truncation

`actions_decided = 0` in all four cycles; `full_context.actions` is empty except cycle 350's single action from the one surviving block. This is **worse than an envelope problem**: truncated cycles lose their *trading decisions* too — those sleeves silently did nothing. Q4 answered: the problem is not isolated to the envelope key; the whole terminal json block is never emitted.

### 5. Quantification

Envelope-capable cycles since Block 3 deployed (PR #2, Jul 12 05:33 UTC): exactly these 4 (349–352, all GLM-5.2, Monday Jul 13 — an earlier draft misread the calendar; 2026-07-13 is a Monday). Sleeve envelopes: 12 → **1 parsed (8.3%), 11 degraded (91.7%)**. Pattern by sleeve: yield_farming 1/4, event_driven 0/4, vol_reversion 0/4 — consistent with "success iff the final completion fits under the cap," not with any verdict-type or sleeve-logic pattern. sector_rotation produced no envelopes (no candidates → LLM never called — correct behavior).

### Q3: yes, the unit tests were fixtures

The Block 3 envelope tests ran `parse_envelope`/`_parse_decision` against synthetic strings I wrote, plus one live GLM smoke test of *tool-calling* (not of long-form final output). Real GLM-5.2 end-of-cycle output — with its reasoning-token budget behavior — was never exercised before deploy. That is the gap: the tests prove the parser parses; they never proved the model, under production context sizes, delivers something parseable.

## Contributing factor discovered: context bloat

Late-turn calls carry **119k–186k input tokens** (playbook + scanner + news tool results accumulating across the 10-turn loop). Two effects: (1) cost — a single 186k-in call is ~$0.26; (2) long contexts push GLM to reason longer, making 4096-out exhaustion more likely. Also noted in passing, non-blocking: per-sleeve `llm_usage_log.caller` attribution has a small race (fire-and-forget persist reads `_current_caller` after it may have advanced), and while lead cycles ARE weekend-guarded (`_is_market_hours`), the sweep/news/reflection crons are NOT — breadth + tier2a processed the full ~6,500-name universe on both Sat Jul 11 and Sun Jul 12 against stale Friday data (compute + API churn + tier2b Llama cost, no GLM cost). The odd 15:06 ET cycle is 9 minutes after the 18:57 UTC deploy restart — likely scheduler misfire on container boot.

## Fix (implemented as proposed)

Ranked, smallest-first; 1+2 are the fix, 3–4 hardening:

1. **Raise `llm_max_tokens` 4096 → 16384** (`config/settings.py`, env-overridable). It's a ceiling, not a target — cost exposure is bounded by the $15/day cap, and the real cost driver is input bloat, not output. This alone probably takes success from 8% to near-100%: even the empty-content cases billed ≤4096, i.e. reasoning wanted ~4–8k total.
2. **Check `finish_reason` in the loop** (`llm_service.py`): on `'length'` at the final turn, log a warning and retry once with an appended user message — "You were cut off. Output ONLY the ```json block (actions + envelope) now." — which is cheap (~200 out tokens) and rescues the decision, not just the envelope. On `'length'` mid-loop, log it (observability).
3. **Persist the failure honestly**: when the retry also fails, stamp the envelope dict with `degraded_reason: "truncated_at_max_tokens"` so the dashboard can distinguish "model cut off" from "model wrote unparseable JSON" — they indict different components.
4. **Follow-up (separate change): trim tool-result bloat** — cap `get_playbook`/`get_scanner_top` payloads in the loop context. Addresses cost and reduces reasoning-budget pressure; also the biggest lever on the $15/day cap headroom.

Explicitly **not** recommended: moving the envelope to its own fenced block (doesn't help — the model dies before emitting *any* block) and loosening Pydantic validation (nothing is being rejected).

## Stakes accounting

The 11 degraded judgments are **permanently lost** (GLM's reasoning content wasn't captured; the visible text was truncated at source). Every additional cycle before the fix loses more — and loses *actions*, not just envelopes. Monday's four cycles decided zero actions in three of four sleeves for this reason. Fix is ~20 lines + a config value; deployable well before the Day-90 checkpoint on the 19th.
