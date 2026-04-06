# Premium Trader — Backlog

Last updated: 2026-04-06

This is the single source of truth for everything that needs to be done to
Premium Trader. The discipline: when you notice something, add it here. When
you ship a batch, mark items done. Don't fix things outside of a planned
batch.

## How to use this

Items are grouped into **batches**. Each batch is sized to fit one Claude
Code prompt. Within a batch, individual tasks are committed separately so
they can be reverted independently.

Status legend:
- `[ ]` not started
- `[~]` in progress
- `[x]` done
- `[?]` blocked or needs investigation

---

## Recommended ship order for today

I'm recommending three batches in this order. Reasoning is in each section.

1. **Batch A — Critical bugs blocking system function** (do first, 1 prompt)
2. **Batch B — Architectural debt that's costing us velocity** (do second, 1 prompt)
3. **Batch C — Observability so you can trust the system** (do third or skip, 1 prompt)

Stop after Batch B if Claude Code usage is getting tight. Batch C is valuable
but not blocking.

---

## BATCH A — Critical bugs blocking system function

**Why this batch first:** Two real bugs are blocking the system from doing
the things it has correctly decided to do. The LLM's reasoning is sound but
its decisions are silently failing. Ship these and the system actually starts
making and managing money.

### A1. Worker routing returns None for legacy positions
**Status:** `[ ]`
**Severity:** Critical
**Evidence:** Today's logs showed 6 close decisions all failing with
`No worker found for position GDXxxxxxx`. The LLM correctly identified that
6 GDX/XBI positions had captured 70%+ profit and should be closed before
weekend gap risk, but `_find_worker_for_position()` couldn't route the close
to a worker because it relies on in-memory `assigned_to` state that gets lost
when the agents container restarts.

**Fix approach:** `_find_worker_for_position()` in `agents/lead_agent.py:989`
should fall back to querying the Trade table by `option_symbol` and reading
`Trade.agent_name` when the in-memory `assigned_to` is empty. The DB has the
answer; we just need to ask it. Bonus: when reading from DB, write the result
back to `opt.assigned_to` so subsequent lookups in the same cycle hit the
in-memory cache.

### A2. Legacy positions have no `assigned_to` at all (data backfill)
**Status:** `[ ]`
**Severity:** High
**Notes:** The 8 currently-open positions were opened by an older code
version. Even after fixing A1 to query the Trade table, those positions need
their `assigned_to` populated. One-shot SQL backfill: `UPDATE trades SET
agent_name='Cash-Secured-Puts' WHERE option_symbol IN (...) AND agent_name IS
NULL;` (the system only ran CSP when these were opened, so we can hardcode
the assignment).

### A3. The 21 legacy "submitted" trades will never reconcile
**Status:** `[ ]`
**Severity:** Medium
**Notes:** Today's reconciler log showed `Trade 1-21 has no order_id —
skipping`. These trades will sit in the DB as `submitted` forever, polluting
performance metrics. Two options: (a) bulk update them to `status='unknown'`
and ignore, or (b) write a one-shot script that queries Alpaca's order
history for the past month and tries to match by symbol+strike+expiration+qty.
**Recommend (a)** — not worth the engineering effort to retroactively fix
paper trades.

---

## BATCH B — Architectural debt killing our velocity

**Why this batch second:** Every bug we've fought in the last week has been
"the two entrypoints drifted" or "I deployed and it crashed because nothing
caught the error before the droplet did." Fix the root causes and stop
fighting these forever.

### B1. Kill `api/state.py` as a separate entrypoint
**Status:** `[ ]`
**Severity:** High (recurring drift bug)
**Evidence:** This drift has caused at least three production bugs in the
past week — missing OrderReconciler in api/state, missing
scanner/strategy_manager in workers, missing VIXService wiring. Every time
we add a new service, we fight the drift battle again.

**Fix approach:** Refactor `main.py` to extract its initialization logic into
a function `build_app_state(broker, mode) -> AppState`. Then `api/state.py`
imports and calls that function instead of duplicating it. One source of
truth, impossible to drift. Should be a single afternoon's work to do
properly. Reference the existing `AppState` class structure so the public
attributes stay the same and the FastAPI routes don't break.

### B2. Add a preflight smoke test script
**Status:** `[ ]`
**Severity:** High (catches deploy bugs in 30 seconds)
**Evidence:** The `pytz` import bug, the order_id AttributeError, the
boolean default migration, the missing httpx — all of these would have been
caught in 30 seconds by a script that imports every module and runs
`alembic upgrade head` against a throwaway SQLite.

**Fix approach:** Create `scripts/preflight.py` that:
1. Imports every top-level module in `agents/`, `services/`, `api/`, `models/`
2. Instantiates each service with mock/None dependencies
3. Creates an in-memory SQLite database and runs `alembic upgrade head`
   against it
4. Exits 0 if everything works, exits 1 with the traceback if anything fails

Then add a one-line sanity check in your deploy routine: `python
scripts/preflight.py && git push`. If preflight fails, the push doesn't
happen and you debug locally instead of on the droplet.

### B3. Add a `make deploy` shortcut
**Status:** `[ ]`
**Severity:** Medium
**Notes:** Right now your deploy is "git push, ssh, git pull, docker compose
up -d --build, docker compose logs --follow." That's five commands across
two machines. A `Makefile` with `make deploy` that does the whole thing in
one command (including running preflight first) would make every future
deploy faster and less error-prone. Optional but high-leverage.

---

## BATCH C — Observability and trust-building

**Why this batch third:** You can only step away from watching the dashboard
constantly if you trust the system. Right now you don't fully, because
several UI components show stale or wrong data. Fix these and you can start
treating Premium Trader as a managed service rather than something you have
to babysit.

### C1. Active Positions card needs to show agent assignment
**Status:** `[ ]`
**Severity:** Medium
**Notes:** When the worker routing bug fires (A1), there's no way to see it
on the dashboard. Adding an `assigned_to` column or badge to the Active
Positions card would surface routing issues immediately.

### C2. Equity chart Y-axis auto-scaling
**Status:** `[ ]`
**Severity:** Low
**Notes:** The chart currently spans $0 to $100k+, which squashes any actual
movement. Should auto-scale to a tighter range based on min/max of visible
data points. Recharts supports this with `domain={['dataMin', 'dataMax']}`.

### C3. Show the LLM's most recent action plan on the dashboard
**Status:** `[ ]`
**Severity:** Medium
**Notes:** Today's logs show the LLM made 9 distinct decisions (6 closes, 2
holds, 1 pause). Right now the dashboard shows the System Assessment text but
not a structured action plan with status indicators. A small "Last Cycle
Actions" card showing each decision and whether it executed successfully
would make routing failures (A1) immediately visible.

---

## DEFERRED — not for today, on the radar

These are real but they're not blocking and they're not architectural debt.
They're things to think about over the next month.

### D1. Two regime classifiers running in parallel
`core/strategy.py` produces `high_vol/normal/low_vol` and
`services/market_regime.py` produces `risk_off/neutral/risk_on`. They both
read VIX from the same VIXService now (after the recent fix), so they
shouldn't drift. But long-term they should be consolidated into a single
authoritative regime that downstream code reads from. Not urgent.

### D2. Frontend `buildEquityData` should be deleted
After Batch C ships and the equity-history endpoint is the source of truth,
`buildEquityData` in DashboardPage.jsx becomes dead code. Clean up.

### D3. Worker pause/resume button on the dashboard
The plumbing now exists (worker_states table, persistent state across
processes). Adding a UI button to pause/resume workers from the dashboard
would let you manually intervene without SSHing into the droplet.

### D4. Mobile push notifications for risk events
Right now Discord notifications work but you mentioned earlier you'd rather
look at the dashboard twice a day and trust the system the rest of the
time. That requires push notifications for: position down >5%, account
equity drops >2%, LLM errors, reconciler errors. Probably 2 hours of work
total, but lets you actually walk away from the dashboard.

---

## OBSERVATIONS — read but do not fix

These are things to look at during observation blocks. Do NOT engineer
against these, just understand them.

### O1. The LLM is starting to cite its own playbook entries in trade decisions
Today's cycle: *"4 DTE Profit Capture Rule: 89.6% profit with 4 DTE in
elevated VIX environment. Playbook rule confidence 0.9."* This is the first
evidence of the learning flywheel actually compounding. Worth pulling all
playbook entries and reading them end-to-end at some point this week.

### O2. The system got concentrated in GDX
8 of 8 open positions are bearish bets on either gold miners (6 GDX) or
biotech (2 XBI). Why did the scanner repeatedly surface the same names? Is
this a feature (high IV in those names is real) or a bug (scanner has bias
toward certain sectors)? Worth understanding before you let this run more
capital.

### O3. The CSP worker has 0% win rate over 21 trades
The performance evaluator just flagged this in today's logs. Two
interpretations: (a) the system is genuinely losing money and the strategy
needs rethinking, or (b) the trades are stuck in `submitted` status and
their P&L is showing as null/zero. Probably (b) — the reconciler hasn't been
working until today. After Batch A ships and reconciliation starts catching
fills, the win rate metric will become meaningful.

### O4. Buying power is at $821 / $97k equity
Almost the entire account is tied up in collateral for the 8 short puts.
This is normal for CSPs but means you can't open new positions until some
close. The LLM correctly identified this and paused all workers. Good
behavior. But it means the system is currently waiting on existing positions
to resolve before it can trade again.
