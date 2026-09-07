# Entry Specification

Single source of truth for **when the pipeline proposes a trade**. If the code
and this document disagree, that is a bug in one of them — say so in the PR.

Status: describes the pipeline as of commit `c22641c` (2026-09-07), plus the
"Conservative" risk changes agreed 2026-09-07 (marked ▶ PENDING — not in code
yet, landing in a separate PR).

Nothing in this pipeline places an order. Every path below ends at a **written
proposal + notification**, and a human confirms and places the trade.

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
             → write proposal to pending_live_orders.json + notify
  → STOP
```

A failure at any gate is logged (`trade_log.jsonl`) and **no proposal is
written**. Some failures are "signal-only" (nothing was wrong, there was just
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

### ▶ INTRADAY REBUILD (agreed 2026-09-07 — to build)

The current signal is hourly-bar machinery: a 200-*hour* VWAP is ~30 trading
days of context, which is a swing-trend filter, not an intraday one. Rebuild:

**Bars.** 5-minute. Fetch the **prior session + today** so `ADX`/`ATR` are warm
at the open; VWAP uses **today only**.

**VWAP.** Switch from a 200-bar rolling VWAP to a **session-anchored VWAP** that
resets each day at the 13:30 UTC open — the standard intraday reference.

**Signal** — all three on the latest *closed* 5-minute bar:

1. **Session-VWAP cross.** Close crosses the session VWAP vs the previous 5-min
   bar. Up → bullish (call); down → bearish (put).
2. **DMI alignment.** `+DI > −DI` (bull) / `−DI > +DI` (bear), 14-period on
   5-min bars.
3. **Trend strength.** `ADX(14) > 20` on 5-min bars.

**Reference levels** (still informational): `stop_distance = 1.5 × ATR(14, 5-min)`
— tighter than the old 2.5×, intraday — `target = 2 × stop_distance`.

**Warm-up.** `ADX(14)` needs ~20 5-min bars. Seeding from the prior session's
last ~40 bars lets signals fire from the open instead of ~9:00 AM PT.

**Parameters (proposed)**

| name | value |
|---|---|
| bar interval | `5min` |
| `VWAP_ANCHOR` | session open (13:30 UTC) |
| `DMI_ADX_LENGTH` | 14 |
| `ADX_MIN` | 20.0 |
| `ATR_STOP_MULT` | 1.5 |
| warm-up seed | prior session, ~40 bars |

<details><summary>Previous (hourly / swing) signal — for reference</summary>

All three on the latest **hourly** bar: 200-bar rolling VWAP cross · `+DI/−DI`
alignment · `ADX(14) > 20`. `VWAP_WINDOW=200`, `MIN_BARS_REQUIRED=210`,
`stop = 2.5×ATR`, `target = 3× that`.
</details>

---

## 3. Strategy C — Pairs Stat-Arb

`pairs_arb_scanner.py` · `pairs_prepare_order.py`

**Universe.** Candidate pairs auto-generated from the same ~399-symbol universe:
a vectorized correlation pre-filter (`|corr| ≥ 0.80` over 250 bars), then a
from-scratch single-lag Dickey-Fuller cointegration test on the survivors
(no `statsmodels` in the sandbox). Index-level instruments (SPX/NDX/VIX)
excluded; index exposure comes via SPY/QQQ/DIA/IWM.

### ▶ INTRADAY REBUILD (agreed 2026-09-07 — to build)

Cointegration on 5-minute noise is statistically weak, so split it in two:

**Daily tier — pick the pairs (slow).** Once per day (piggy-back on the
Market-Open Health Check), run the correlation pre-filter + Dickey-Fuller
cointegration on **hourly** bars over ~60–90 sessions. Output: the day's list of
tradeable pairs, each with its hedge ratio `β` and cointegration `p`. Written to
a `pairs_today.json` the intraday tier reads. Cointegration keeps its longer
horizon — only the *entry trigger* moves intraday.

**Intraday tier — trigger the entry (fast).** Every 15–30 min, for each pair in
`pairs_today.json`:

1. Spread `= a − β·b` using the day's fixed `β`.
2. Rolling z-score over **60 × 5-minute bars** (~5 hours).
3. Enter when **`|z| ≥ 2.0`** (the pair already cleared `p < 0.10` in the daily
   tier). `z ≤ −2` → long A / short B; `z ≥ +2` → short A / long B.
4. Two-leg option package, 50/50 budget split, counts as **one** open position.

**Exit** (see EXIT_SPEC §5.3): target `z → 0`, abandon at `z = ±3.5`, plus the
end-of-day flatten. No per-contract premium stop.

**Parameters (proposed)**

| name | value |
|---|---|
| daily-tier bars | `hour`, ~60–90 sessions |
| intraday-tier bars | `5min` |
| `Z_WINDOW` | 60 (5-min bars) |
| `Z_ENTRY` | 2.0 |
| `COINT_P_MAX` | 0.10 (daily tier) |
| `CORR_THRESHOLD` | 0.80 (daily tier) |
| hedge ratio `β` | fixed for the day, from the daily tier |

<details><summary>Previous (all-hourly) signal — for reference</summary>

OLS hedge ratio + 60-*hourly*-bar z-score, cointegration `p < 0.10`, entry
`|z| ≥ 2.0`. `Z_WINDOW=60`, `CORR_THRESHOLD=0.80`.
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

| | current | ▶ PENDING (Conservative) |
|---|---|---|
| `max_loss_pct` | **0.60** | **0.10** |

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

| check | current | ▶ PENDING (Conservative) |
|---|---|---|
| Affordability | `cost ≤ 85% of buying power` | unchanged |
| Premium floor | `cost ≥ $15` | unchanged |
| Spread | `≤ 10% of ask` | unchanged |
| Position cap | `open positions < 5` | unchanged |
| Daily drawdown | `today P&L > −15% of equity` | **`> −8% of equity`** |
| VIX regime | `VIX > 25 → budget × 0.5` | unchanged |

### 4.7 Simulate — `review_option_order`
Prices the ticket, surfaces broker alerts. **Never submits.** Result is attached
to the proposal.

### 4.8 Proposal
Appended (never overwritten) to `pending_live_orders.json` with a planned
stop-loss ticket attached (see EXIT_SPEC §1), `status = awaiting_confirmation`.
Notification sent. Expires unconfirmed after **45 min**
(`live_expire_stale_orders.STALE_MINUTES`).

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
