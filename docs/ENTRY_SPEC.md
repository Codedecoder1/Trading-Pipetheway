# Entry Specification

Single source of truth for **when the pipeline proposes a trade**. If the code
and this document disagree, that is a bug in one of them — say so in the PR.

Status: describes the pipeline as of commit `c22641c` (2026-09-07), plus the
"Conservative" risk changes agreed 2026-09-07 (marked ▶ PENDING — not in code
yet, landing in a separate PR).

Nothing in this pipeline places an order. Every path below ends at a **written
proposal + notification**, and a human confirms and places the trade.

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

**Signal** — all three must hold on the **latest hourly bar**:

1. **VWAP-200 cross.** Close crosses the rolling 200-bar VWAP relative to the
   previous bar. Up-cross → bullish; down-cross → bearish.
2. **DMI alignment.** `+DI > −DI` for a bullish cross; `−DI > +DI` for bearish.
   (14-period, Wilder-smoothed.)
3. **Trend strength.** `ADX(14) > 20`.

**Reference levels** computed and reported, **not enforced** (see EXIT_SPEC):
`stop_distance = 2.5 × ATR(14)` · `stop = close ∓ stop_distance` ·
`target = close ± 3 × stop_distance`.

**Parameters**

| name | value |
|---|---|
| `VWAP_WINDOW` | 200 bars |
| `DMI_ADX_LENGTH` | 14 |
| `ADX_MIN` | 20.0 |
| `MIN_BARS_REQUIRED` | 210 |

---

## 3. Strategy C — Pairs Stat-Arb

`pairs_arb_scanner.py` · `pairs_prepare_order.py`

**Universe.** Candidate pairs auto-generated from the same ~399-symbol universe:
a vectorized correlation pre-filter (`|corr| ≥ 0.80` over 250 bars), then a
from-scratch single-lag Dickey-Fuller cointegration test on the survivors
(no `statsmodels` in the sandbox). Index-level instruments (SPX/NDX/VIX)
excluded; index exposure comes via SPY/QQQ/DIA/IWM.

**Signal**

1. OLS hedge ratio `a ~ const + β·b`; spread `= a − β·b`.
2. Rolling z-score of the spread over a **60-bar** window.
3. Entry when **`|z| ≥ 2.0`** *and* cointegration `p < 0.10`.
   - `z ≤ −2.0` → long leg A / short leg B.
   - `z ≥ +2.0` → short leg A / long leg B.
4. Built as a **two-leg option package**, budget split 50/50 across legs,
   counts as **one** open position.

**Exit is defined here, not in exit_engine**: target `z = 0.0`, abandon at
`z = ±3.5`. No per-contract premium stop on a pairs package.

**Parameters**

| name | value |
|---|---|
| `Z_WINDOW` | 60 |
| `Z_ENTRY` | 2.0 |
| `COINT_P_MAX` | 0.10 |
| `CORR_THRESHOLD` | 0.80 |

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

### 4.4 Expiration — `select_expiration.py`
First listed expiration **10–45 calendar days** out (`MIN_DTE = 10`,
`MAX_DTE = 45`). If nothing is ≥ 10 days out → `signal_only`.

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

1. **Schedule.** Code comments say SMC = Mon/Tue/Thu/Fri, VWAP/DMI = Wed only,
   Pairs = Thu. The live tasks appear to run all three daily/hourly. Which is
   intended? This doc describes *signal logic*, not the schedule — the schedule
   lives in the task definitions.
2. **VWAP/DMI + Pairs expiration.** They previously targeted ~21 DTE; they now
   use the shared 10–45 window (first in range). Confirmed "leave it" 2026-09-07;
   noted here so it is not forgotten.
3. **SMC bar interval.** `detect_smc_manipulation_reversal` is interval-agnostic;
   the original design used 15-minute bars. Confirm what the live task feeds it.
