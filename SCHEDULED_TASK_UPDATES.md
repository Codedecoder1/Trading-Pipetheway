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
| Daily Market-Open Health Check | `32 13 * * 1-5` | unchanged (Pairs is self-contained now — no daily-tier step) |
| 10:05am Progress Recap | `5 17 * * 1-5` | unchanged |
| Market-Close Daily Summary | `5 20 * * 1-5` | also runs `reporting.py` (embed scorecard in the notification) |

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

### E. Pairs — self-contained, one task, no git, no daily step

Git push doesn't work from the task container, so Pairs runs `--self-contained`:
one firing does everything. **No Market-Open step, no `pairs_today.json`, no
cross-firing state.**

**`Pairs Stat-Arb Signal Monitor` task** (×2 siblings, `:00` / `:30`), prompt:

> Read `pairs_universe.json` from the repo (~65 curated symbols). Stage
> **5-minute** bars (`interval="5minute"`) for those symbols, **~8 sessions
> deep** (≥ ~450 bars/symbol), into `pairs_5min_bars.json` as
> `{symbol:[{close_price,begins_at,...},...]}`. Run
> `python3 pairs_arb_scanner.py pairs_5min_bars.json --self-contained`. On a
> hit, continue into the existing `resolve_pairs_leg.py` ×2 →
> `pairs_prepare_order.py` path.

~65 symbols × one deep 5-min fetch = a handful of batched `get_equity_historicals`
calls per firing. The scanner runs the correlation → cointegration → z-score
funnel itself each time; a pair that decouples drops out automatically.

To change the candidate list: edit `pairs_universe.json`, merge a PR, re-pin.

### F. NEW TASK — `Exit Monitor` (×2 siblings, `:00` / `:30`)

Every ~30 min, 13:30–20:05 UTC, Mon–Fri. Same STANDING RULE. Prompt:

> 1. `get_option_positions` (nonzero) + `get_option_orders` (all recent) for
>    the Agentic account. If no open option positions, stop.
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

**Push creds:** the task container **cannot push** (2026-09-07 test — a
diagnostic push produced no branch on the repo). Consequences:
- Pairs: solved — it's `--self-contained` now (§E), no git needed.
- `RESULTS.md` on GitHub: the Market-Close task can't commit it. Either read
  the scorecard from the notification and skip GitHub, or run
  `python3 reporting.py --commit` from an interactive checkout after the close.
  (The scorecard in the notification is the same content.)

---

## Trading-days schedule — DECIDED 2026-09-07: all 5 weekdays

All three signal strategies (SMC, VWAP/DMI, Pairs) run **Monday–Friday**. The
old SMC = Mon/Tue/Thu/Fri · VWAP/DMI = Wed-only · Pairs = Thu split is retired —
the strategies are now the same intraday shape and independent, and the
position cap / budget gates handle any overlap. Every cron in the task table
above already ends in `* * 1-5`; make sure no task carries a leftover day
restriction (a Wed-only or Thu-only clause) from the old design.
