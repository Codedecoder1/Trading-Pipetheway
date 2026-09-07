# Scheduled-task updates needed alongside this branch

Code changes in `tune-sizing-expiry-stops` don't take effect until the 6
scheduled tasks (Chat / Cowork -> Scheduled) are updated:

## 1. Re-pin the commit

Each task clones a **pinned commit** of `Codedecoder1/Trading-Pipetheway`, not
`main`. After this branch merges, update every task's pinned commit hash to the
new merge commit. (If the tasks actually track `main`/`HEAD`, skip this — but
confirm, don't assume.)

## 2. Expiration step — the 3 signal-monitor task prompts

**VWAP/DMI**, **SMC**, and **Pairs** monitor prompts currently say to fetch
"the nearest expiration's contract chain." Replace that with:

> After a signal passes Layer 1 and the guardrail, fetch the underlying's
> available option expiration dates. Run:
> `python3 resolve_expiration.py --expirations-json '["YYYY-MM-DD", ...]'`
> Use the `expiration` value it returns (first expiration ~2 weeks out). If it
> returns `null`, log the signal as signal-only (`event
> "signal_only_not_executed"`, reason from the `note`) and stop — do not
> prepare an order. Otherwise fetch THAT expiration's full contract chain and
> continue into `resolve_contract.py` / `live_prepare_order.py` as before.

(Pairs uses `resolve_pairs_leg.py` per leg — apply the same
`resolve_expiration.py` step before resolving each leg's contract.)

## 3. Nothing else changes

- Sizing (85% / 15%), execution cutoff (20:00 UTC), stale-order window (45 min),
  ATM-first selection, and the stop-loss ticket in the proposal notification are
  all pure code changes — they flow through automatically once the commit is
  re-pinned.
- The **STANDING RULE** (never call `place_option_order` / `place_equity_order`
  / `review_equity_order`) is untouched and stays verbatim in every task.

## 4. Timezone sanity check (Pacific)

| Task | Should fire (America/Los_Angeles) |
|---|---|
| Daily Market-Open Health Check | 6:32 am, Mon–Fri |
| VWAP/DMI Daily Signal Monitor | 6:30 am–1:00 pm, :30 past the hour |
| SMC Bot Live Signal Monitor | 6:30 am–1:00 pm, :45 past the hour |
| Pairs Stat-Arb Signal Monitor | 6:30 am–1:00 pm, :15 past the hour |
| 10:05am Progress Recap | 10:05 am, Mon–Fri  (last run FAILED 2026-09-04 — watch the next one) |
| Market-Close Daily Summary | 1:05 pm, Mon–Fri |
