# Scheduled-task updates — running checklist

Code in this repo does nothing until the 6 scheduled tasks (Chat / Cowork →
Scheduled) are updated. Each task clones a **pinned commit**, so after every
merge to `main`:

1. **Re-pin** all 6 tasks to the new merge commit.
2. Apply any prompt changes below that aren't done yet.
3. **Never touch** the STANDING RULE (no `place_option_order` /
   `place_equity_order` / `review_equity_order`) — leave it verbatim.

Tasks: `SMC Bot Live Signal Monitor`, `VWAP/DMI Daily Signal Monitor`,
`Pairs Stat-Arb Signal Monitor`, `Daily Market-Open Health Check`,
`10:05am Progress Recap`, `Market-Close Daily Summary`.

---

## Prompt changes

### A. Expiration step — 3 signal-monitor tasks — ✅ done (PR 1 era)

Each fetches expirations and runs
`python3 resolve_expiration.py --expirations-json '[...]'`, uses the returned
`expiration`, logs signal-only if it's `null`.

### B. Cadence → every 15 minutes — ☐ TODO

All three signal tasks currently fire hourly (runbook says SMC = "every 30
min"). Set the schedule of **SMC**, **VWAP/DMI**, and **Pairs** to fire every
**15 minutes** during 13:30–19:00 UTC (6:30 AM–12:00 PM PT), Mon–Fri.
(No new entries after 19:00 UTC — the code enforces this via `EXECUTION_CUTOFF`,
but there's no point firing the task after noon PT.)

### C. VWAP/DMI task — fetch 5-minute bars — ☐ TODO (needed for PR 3)

The VWAP/DMI monitor prompt must stage, per symbol:

> `get_equity_historicals` with **interval = "5minute"**, covering the **prior
> regular session plus today so far** (roughly the last ~80 5-minute bars).
> Write them to `vwap_dmi_raw/<batch>.json` in the shape
> `{"data": {"results": [{"symbol": "...", "bars": [ {open_price, high_price,
> low_price, close_price, volume, begins_at}, ... ]}]}}`, then run
> `python3 vwap_dmi_screener.py`.

If the prompt currently asks for hourly bars, that is now a bug — the screener
resamples nothing and expects 5-minute input.

### D. SMC task — confirm 5-minute bars — ☐ TODO (verify)

`dry_run_check.py` already expects 5-minute bars (it resamples to 5/10/30).
Confirm the SMC task's `get_equity_historicals` call requests `"5minute"`, not
hourly. If it's hourly, the 10/30-min resample produces garbage.

### E. Pairs task — two-tier — ☐ TODO (needed for PR 4)

**E1. Daily tier — add to the `Daily Market-Open Health Check` task prompt:**

> Once, near the open: stage **hourly** bars (`interval="hour"`) for the
> `watchlist_universe.json` symbols, ~250+ bars each (≈ 60–90 sessions), into
> `pairs_hourly_bars.json` as `{symbol: [ {close_price, begins_at, ...}, ... ]}`.
> Run `python3 pairs_daily_tier.py pairs_hourly_bars.json`. It writes
> `pairs_today.json` (the day's cointegrated pairs + fixed hedge ratios). Report
> how many pairs qualified.

**E2. Intraday tier — the `Pairs Stat-Arb Signal Monitor` task prompt:**

> Every 15 min: stage **5-minute** bars (`interval="5minute"`) for just the
> symbols named in `pairs_today.json` (last ~5–6 hours, ≥ 65 bars each) into
> `pairs_5min_bars.json`, same shape. Run
> `python3 pairs_arb_scanner.py pairs_5min_bars.json`. If `pairs_today.json` is
> missing (daily tier hasn't run), the scanner logs that and does nothing —
> that's expected before the open.

Then continue into the existing `resolve_pairs_leg.py` × 2 → `pairs_prepare_order.py`
package-proposal path unchanged.

---

## Trading-days schedule — ☐ confirm

Code comments say SMC = Mon/Tue/Thu/Fri, VWAP/DMI = Wed only, Pairs = Thu. The
live tasks appear to run all three every day. Decide and make the task
schedules match the intent.
