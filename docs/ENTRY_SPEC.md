# Entry Specification

Single source of truth for **when the pipeline proposes a trade**. If the code
and this document disagree, that is a bug in one of them — say so in the PR.

Status: current through PR 7 (2026-09-07) — Conservative dials, noon cutoff, the
VWAP/DMI + Pairs intraday rebuilds, `exit_manager.py`, `reporting.py`, and the
stateless / no-shared-filesystem rework are all in code.

**No task places an order.** Every path below ends at a **notification with a
full bracket ticket**, and a human (or an interactive session) confirms and
places the buy + the two resting orders.

**Trading style (agreed 2026-09-07): all three strategies are intraday.** Signal
on minute bars → enter a call or put → take profit or stop out **the same
session**. The 10–45 DTE expiration (§4.4) is bought as a **theta / pin-risk
cushion**, not a holding period — the position is not meant to be held
overnight. Exit management is covered in `EXIT_SPEC.md`.

---

## 0. The shape of every entry

```
scheduled task fires
  → refresh universe (live Robinhood scan)
  → fetch bars for surviving symbols (get_equity_historicals)
  → run the strategy detector
  → on a hit:  Layer-1 filters → loss guardrail → execution cutoff
             → pick expiration → pick contract → risk gate → simulate
             → notify with the bracket ticket
  → STOP
```

A failure at any gate is logged (best-effort, this firing only) and **no
proposal is sent**. Some failures are "signal-only" (nothing was wrong, there
no runway) and some are "rejected" (a risk limit was hit).

---

## 1. Strategy A — SMC Volume Profile

`smc_engine.py` · `dry_run_check.py`

**Universe.** Live Robinhood scan "SMC Bot – Live Movers Gate":
`price ≥ $10` · `30-day average volume ≥ 1.5M shares` · `|% change from prior
close| > 2.7%`. Unioned with 12 fixed ETFs: `SPY QQQ IWM DIA · SMH XLF XLE XBI ·
TQQQ SQQQ SOXL LABU`. Falls back to the ~267-symbol static universe only if the
live universe file is missing.

**Signal** (`detect_smc_manipulation_reversal`), on the strategy's bar interval:

1. Take the consolidation window = the 12 bars ending 2 bars back.
2. If that window is *consolidating* (high-low spread ≤ 1.5% of the low) →
   `NO_ENTRY`. Signals are only taken out of a defined range.
3. Compute the **Point of Control** (POC) — the price level with the most
   traded volume, with each bar's volume spread across its whole high-low range.
4. **Bullish** (`BULLISH_POC_RETEST` → buy call): price swept **below** the
   consolidation low on the previous or current bar, **and** the current close
   is back **at/above** the POC while the previous close was below it.
5. **Bearish** (`BEARISH_POC_RETEST` → buy put): mirror — swept **above** the
   consolidation high, current close back **at/below** POC, previous close above.
6. Otherwise `NEUTRAL` — trending but no valid retest yet, no trade.

**Parameters**

| name | value | meaning |
|---|---|---|
| `consolidation_bars` | 12 | window length for the range / POC |
| consolidation threshold | 1.5% | range width that counts as "still consolidating" |
| POC bins | 20 | volume-profile resolution |

---

## 2. Strategy B — VWAP-200 / DMI / ADX

`vwap_dmi_screener.py` · `vwap_dmi_indicators.py`

**Universe.** `watchlist_universe.json` — a live scan snapshot: Stock+ETF ·
`price ≥ $5` · `30-day average options volume ≥ 500`. ~399 symbols (Robinhood's
scanner backend caps near 400). Falls back to a fixed 24-symbol list if the file
is missing.

### Signal — intraday (rebuilt 2026-09-07, PR 3 · REVISION 18)

**Bars.** 5-minute. The task fetches the **prior session + today** so `ADX(14)`
and `ATR(14)` are warm from the open; the session VWAP still starts fresh each
day (it groups by UTC date, so the prior session doesn't contaminate it).

**VWAP.** `session_vwap()` — a session-anchored VWAP that resets at each UTC
day's first bar. Replaces the old 200-*hour* rolling VWAP (~30 trading days of
context — a swing filter, not an intraday one).

**Signal** — all three, evaluated on the latest *closed* 5-minute bar, with the
cross required to be between two of **today's** bars:

1. **Session-VWAP cross.** Close crosses `session_vwap` vs the previous 5-min
   bar. Up → call, down → put.
2. **DMI alignment.** `+DI > −DI` (bull) / `−DI > +DI` (bear), 14-period.
3. **Trend strength.** `ADX(14) > 20`.

The screener re-runs every 15 min, so it catches the cross in the cycle it
happens — it does not fire on a stale cross from earlier in the session.

**Reference levels** (informational; real exits are in EXIT_SPEC):
`stop_distance = 1.5 × ATR(14, 5-min)`, `target = 2 × stop_distance`.

**Parameters** (`vwap_dmi_screener.py`)

| name | value |
|---|---|
| `BAR_INTERVAL` | `5min` |
| VWAP | `session_vwap()`, resets each UTC day |
| `DMI_ADX_LENGTH` | 14 |
| `ADX_MIN` | 20.0 |
| `ATR_STOP_MULT` | 1.5 |
| `ATR_TARGET_MULT` | 2.0 (× stop_distance) |
| `MIN_BARS_REQUIRED` | 40 (warm-up seed) |
| `MIN_SESSION_BARS` | 2 |

<details><summary>Previous (hourly / swing) signal — for reference</summary>

All three on the latest **hourly** bar: 200-bar rolling VWAP cross · `+DI/−DI`
alignment · `ADX(14) > 20`. `VWAP_WINDOW=200`, `MIN_BARS_REQUIRED=210`,
`stop = 2.5×ATR`, `target = 3× that`.
</details>

---

## 3. Strategy C — Pairs Stat-Arb

`pairs_arb_scanner.py` · `pairs_prepare_order.py`

### Signal — self-contained (LIVE, PR 8 · REVISION 6)

The two-tier design (§ below) needs a git push each morning, which the
scheduled-task container cannot do. The **live path is `--self-contained`**:
one firing, no state, no git.

**Universe.** `pairs_universe.json` — a **curated ~65-symbol list** of
economically-linked names (sector ETFs, substitutes, same-industry majors,
index proxies), NOT the 399-symbol liquidity screen. Random names that merely
correlate over a few hundred bars are usually spurious — a hand-picked menu
keeps the cointegration test separating signal from noise. Edit the file +
merge a PR to change the menu (rare); which pairs actually trade is recomputed
every firing.

**Each firing** (`scan_pairs_self_contained()`), from ~8 sessions of 5-minute
bars per symbol:

1. **Correlation pre-filter** — `|corr| ≥ 0.80` over the last `CORR_WINDOW_5MIN
   = 300` bars.
2. **Cointegration** — single-lag Dickey-Fuller on the full aligned series,
   `≥ COINT_MIN_5MIN_BARS = 400` bars, keep `p < 0.10`. On ~8 sessions of 5-min
   data this tests mean reversion on the hours-to-days horizon — which is the
   horizon an intraday-exit trade cares about.
   *(ADF residual subtracts the OLS intercept so it is genuinely zero-mean.)*
3. **Z-score** — over the last `Z_WINDOW_5MIN = 60` bars, hedge ratio `β`
   re-fit this firing. Enter at **`|z| ≥ 2.0`**: `z ≤ −2` → long A / short B;
   `z ≥ +2` → short A / long B.
4. Two-leg option package, 50/50 budget split, counts as **one** open position.

**Exit** (EXIT_SPEC §5.3): target `z → 0`, abandon at `z = ±3.5`, plus the
end-of-day flatten. No per-contract premium stop.

**Parameters**

| name | value |
|---|---|
| universe | `pairs_universe.json` (~65 curated) |
| bars | `5min`, ~8 sessions deep |
| `CORR_WINDOW_5MIN` / `CORR_THRESHOLD` | 300 / 0.80 |
| `COINT_MIN_5MIN_BARS` / `COINT_P_MAX` | 400 / 0.10 |
| `Z_WINDOW_5MIN` / `Z_ENTRY` | 60 / 2.0 |

<details><summary>Two-tier path (needs push creds — not the live default)</summary>

`pairs_daily_tier.py --commit` runs the correlation + cointegration funnel on
**hourly** bars (`MIN_HOURLY_BARS = 250`) once near the open, commits
`pairs_today.json` (qualified pairs + fixed `β`) to the repo;
`scan_pairs_intraday()` reads it back via `git show origin/main:pairs_today.json`
and runs the z-score with the fixed `β`. Kept for whenever the task container
gets push credentials. `scan_pairs()` (all-in-one hourly) remains for backtests.
</details>

---

## 4. Shared gates (every strategy, in order)

### 4.1 Layer-1 filters — `contract_filters.py`
- **Volume spike** present (enforced; a missing volume series *fails*, not skips).
- **Session-time cutoff** — signal timestamp ≤ `SESSION_TIME_CUTOFF` (20:00 UTC).
  Controls whether a signal is *logged* at all.
- **Not consolidating** — same range test as the SMC detector.

### 4.2 Daily loss guardrail — `pnl_guardrail.py`
Halt **all new** trades for the rest of the day once today's realized loss
reaches a fraction of day-start buying power.

| | value |
|---|---|
| `max_loss_pct` | **0.10** (was 0.60 — changed in PR "risk dials", 2026-09-07) |

### 4.3 Execution cutoff — `contract_filters.check_execution_time`
Signal timestamp ≤ `EXECUTION_CUTOFF` (**20:00 UTC** as of REVISION 11).
A later signal is logged `signal_only_not_executed` — no proposal.

▶ **DECIDED 2026-09-07: drop back to `19:00:00 UTC` (12:00 PM PT).** REVISION 11
raised it to the session close only for the swing model. With same-day exits, a
signal needs runway before the close to work a target/stop, so no new entries
after noon Pacific. (`SESSION_TIME_CUTOFF` stays at 20:00 — a signal after noon
is still *logged*, just not traded.)

### 4.4 Expiration — `select_expiration.py`
First listed expiration **10–45 calendar days** out (`MIN_DTE = 10`,
`MAX_DTE = 45`). If nothing is ≥ 10 days out → `signal_only`.
Kept as-is (confirmed 2026-09-07): the DTE cushion is deliberate even though
the trade is closed same-day — it keeps theta and pin risk off the position
during the hours it is open.

### 4.5 Contract selection — `contract_selector.py`
ATM first (closest `|delta|` to 0.50). If ATM's `ask × 100` exceeds the budget,
step down to the `0.25–0.35` delta OTM strike closest to `0.30` that fits.
Forced-OTM path is disabled (`SMALL_ACCOUNT_PRICE_THRESHOLD = 1000`).

### 4.6 Risk gate — `live_risk_checks.run_all_checks` — **all must pass**

| check | rule |
|---|---|
| Affordability | `cost ≤ 85% of buying power` |
| Premium floor | `cost ≥ $15` |
| Spread | `≤ 10% of ask` |
| Position cap | `open positions < 5` |
| Daily drawdown | `today P&L > −8% of equity` (was −15% — changed 2026-09-07) |
| VIX regime | `VIX > 25 → budget × 0.5` |

### 4.7 Simulate — `review_option_order`
Prices the ticket, surfaces broker alerts. **Never submits.** Result is attached
to the proposal.

### 4.8 Proposal — a 3-order bracket
`live_prepare_order.py` prints the proposal as a **bracket** (see EXIT_SPEC §1):

1. **Entry** — limit BUY to open @ the ask
2. **Stop-loss** — resting `stop_market` SELL, `entry − 10%`, GTC
3. **Take-profit** — resting `limit` SELL, `entry + 30%`, GTC (half on a ≥2-lot)

At confirmation the human (or an interactive session) places all three — buy
first, the two resting orders right after it fills. The resting stop and TP are
what let the Exit Monitor run at 30-minute cadence. `pending_live_orders.json`
is still written for that firing's own bookkeeping, but it does not persist and
nothing reads it later — the human acts on the notification text.

---

## 5. Open questions for review

**Decided 2026-09-07:**
- Execution cutoff → **19:00 UTC / noon PT** (§4.3).
- **VWAP/DMI and Pairs rebuilt around minute bars** — designs in §2 and §3 above.

**Still task-side (Chat interface, not this repo) — please confirm:**

1. **Task cadence** — all three signal tasks fire every **15–30 min** during
   market hours, not hourly. Runbook says SMC = "every 30 min"; task list shows
   hourly. Pick 15 or 30.
2. **SMC bars** — confirm the SMC task's `get_equity_historicals` call requests
   **5-minute** bars (hourly input silently breaks the 10/30-min resample).
3. **Schedule (days).** Code comments say SMC = Mon/Tue/Thu/Fri, VWAP/DMI = Wed
   only, Pairs = Thu; the live tasks appear to run all three every day. Confirm.
