# Scheduled-task setup — running checklist

Updated 2026-09-07 after two platform facts were confirmed:

1. **A single scheduled task cannot fire more than once per hour.** Sub-hourly
   cadence = several offset hourly tasks ("fan-out").
2. **Scheduled firings share no filesystem** — each runs in a fresh, empty
   container. Nothing written by one firing (or one task) is visible to
   another. State must come from Robinhood, or be committed to the repo.

Every task clones a **pinned commit**. After each merge to `main`, re-pin all
tasks to the new merge commit. **Never touch the STANDING RULE** (no
`place_option_order` / `place_equity_order` / `review_equity_order`).

---

## Task list (target state)

| task | cron (UTC) | notes |
|---|---|---|
| SMC Bot Live Signal Monitor `:00` | `0 14-18 * * 1-5` | + 1 sibling at `:30` |
| SMC Bot Live Signal Monitor `:30` | `30 13-18 * * 1-5` | sibling, identical prompt |
| VWAP/DMI Signal Monitor `:00` | `0 14-18 * * 1-5` | + 1 sibling at `:30` |
| VWAP/DMI Signal Monitor `:30` | `30 13-18 * * 1-5` | sibling |
| Pairs Stat-Arb Signal Monitor `:00` | `0 14-18 * * 1-5` | + 1 sibling at `:30` |
| Pairs Stat-Arb Signal Monitor `:30` | `30 13-18 * * 1-5` | sibling |
| Exit Monitor `:00` | `0 14-20 * * 1-5` | + 1 sibling at `:30` |
| Exit Monitor `:30` | `30 13-19 * * 1-5` | sibling |
| Daily Market-Open Health Check | `32 13 * * 1-5` | also runs `pairs_daily_tier.py --commit` |
| 10:05am Progress Recap | `5 17 * * 1-5` | unchanged |
| Market-Close Daily Summary | `5 20 * * 1-5` | also runs `reporting.py` |

**2 signal siblings, not 4; 2 Exit Monitor siblings, not 12.** The bracket
(below) puts the fast exits at the broker, so 30-minute cadence is enough.
**Delete any extra siblings already created.**

---

## Prompt changes

### A. Expiration step — 3 signal-monitor tasks — done (repin only)

Already call `resolve_expiration.py`. No change beyond the repin.

### B. The BRACKET — entry-confirmation flow — NEW, important

`live_prepare_order.py` now prints the proposal as a **3-order bracket**: the
buy, a resting **−10% stop-market GTC**, and a resting **+30% limit GTC**.
When you confirm an entry, place **all three** (buy first; stop + take-profit
right after it fills). Whoever handles confirmation — you in the app, or an
interactive Claude session — must place the two resting orders, not just the
buy. This is what lets the Exit Monitor run at 30-minute cadence safely.

### C. VWAP/DMI task — fetch 5-minute bars

Stage `get_equity_historicals` with `interval="5minute"`, prior session + today
(~80 bars/symbol), into `vwap_dmi_raw/<batch>.json` shaped
`{"data":{"results":[{"symbol":"...","bars":[{open_price,high_price,low_price,close_price,volume,begins_at},...]}]}}`,
then `python3 vwap_dmi_screener.py`. **Not hourly** — hourly input breaks it.

### D. SMC task — confirm 5-minute bars

Verify its `get_equity_historicals` call uses `"5minute"`.

### E. Pairs — two tiers, handed off through git

**E1. `Daily Market-Open Health Check` task** — add:

> Stage **hourly** bars (`interval="hour"`, ≥250/symbol) for the
> `watchlist_universe.json` symbols into `pairs_hourly_bars.json`
> (`{symbol:[{close_price,begins_at,...},...]}`). Run
> `git fetch origin main` then
> `python3 pairs_daily_tier.py pairs_hourly_bars.json --commit`. It computes
> the day's cointegrated pairs and **commits `pairs_today.json` to the repo**.
> Report how many qualified. (If the commit fails — no push creds — say so;
> the intraday tier then has nothing and trades no pairs that day.)

**E2. `Pairs Stat-Arb Signal Monitor` task** — the prompt must start with
`git fetch origin main` (so `git show origin/main:pairs_today.json` inside
`pairs_arb_scanner.py` sees today's file). Then stage **5-minute** bars for the
symbols in `pairs_today.json` (≥65/symbol) into `pairs_5min_bars.json` and run
`python3 pairs_arb_scanner.py pairs_5min_bars.json`. Then the existing
`resolve_pairs_leg.py` ×2 → `pairs_prepare_order.py` path.

### F. NEW TASK — `Exit Monitor` (×2 siblings, `:00` / `:30`)

Every ~30 min, 13:30–20:05 UTC, Mon–Fri. Same STANDING RULE. Prompt:

> 1. `get_option_positions` (nonzero) + `get_option_orders` (all recent) for
>    account 805015518. If no open option positions, stop.
> 2. Per open position build a dict with the fields in `exit_manager.py`'s
>    docstring. Derive the booleans from the order history:
>    - `has_resting_stop` — an open stop-market SELL exists for this option
>    - `has_resting_tp` — an open limit SELL exists for this option
>    - `has_pending_close` — any other working SELL on this option
>    - `tp1_filled` — a partial close SELL on this option has already filled
>    - `quantity` — the CURRENTLY OPEN contract count
>    Get `current_bid/ask/mark` from `get_option_quotes`.
> 3. Optional thesis check: re-fetch recent 5-min candles, re-run the entry
>    detector; set `thesis_broken` / `underlying_consolidating`.
> 4. For any open pairs package, pass `{pair, current_z, leg_a{...}, leg_b{...},
>    has_pending_close}`.
> 5. Run `python3 exit_manager.py --positions-json '[...]' --pairs-json '[...]'
>    --now-utc <ISO> --session-close-utc <today>T20:00:00Z`.
> 6. Send me every ticket it prints. **Place nothing.**

`exit_manager.py` is fully stateless — no `exit_state.json`, nothing to persist.

### G. `Market-Close Daily Summary` task — run `reporting.py`

After the recap, build inputs from Robinhood (`get_realized_pnl` spans →
`--realized-json`; `get_pnl_trade_history` → `--closed-trades-json` + optional
`win_rate`; `get_portfolio` + `get_option_positions` + quotes → `--account-json`),
run `python3 reporting.py --now-utc <ISO> --realized-json '…' --closed-trades-json '…' --account-json '…'`,
and put the printed scorecard into the summary notification.

**Push creds question** (still open): if this task's container can push to
`Codedecoder1/Trading-Pipetheway`, add `--commit` (and to E1's
`pairs_daily_tier.py` call). If not: `pairs_today.json` handoff **won't work**
from the task — the daily tier would need to run from an interactive checkout
each morning instead — and `RESULTS.md` gets committed from an interactive
session. **Confirm this first; it determines whether the Pairs strategy can run
unattended at all.**

---

## Trading-days schedule — confirm

Code comments say SMC = Mon/Tue/Thu/Fri, VWAP/DMI = Wed only, Pairs = Thu; the
tasks seem to run all three daily. Decide and set the crons to match.
