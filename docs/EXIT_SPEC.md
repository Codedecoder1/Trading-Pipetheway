# Exit Specification

Single source of truth for **how a position should be closed**.

Status: **the intraday rebuild is complete** (PRs 1–6, 2026-09-07). Exits are
managed live by `exit_manager.py` (notify-and-confirm); `reporting.py` produces
`RESULTS.md`.

---

## 1. What actually happens today

Every **entry** proposal notification prints two *planned* tickets the human
places by hand after the fill (`exit_manager.py`, §5, then watches the position
live and proposes the actual close):

| ticket | type | trigger / limit | TIF |
|---|---|---|---|
| Stop-loss | `stop_market` | `entry ask − 10%`, rounded to the cent | GTC |
| Take-profit | `limit` | `entry ask + 30%` | GTC |

`compute_hard_stop_price()` / `compute_take_profit_price()` compute the numbers
(`HARD_STOP_PCT = 0.10`, `TAKE_PROFIT_PCT = 0.30`). On a ≥2-lot the take-profit
sells half and keeps a runner; on a 1-lot it closes the whole position. Nothing
places these automatically — if you do not place the stop yourself, the
position has no protection until `exit_manager.py`'s next 5-minute pass catches
it and proposes the close.

---

## 2. The exit model that `exit_engine.py` *simulates* (not live)

`simulate_hybrid_trade_exit()` — used in backtesting only. It is the intended
shape of a managed exit, and the starting point for `exit_manager.py`.

**Phase 1 — entry → first take-profit.** Checked every bar, in this priority:

1. **Hard stop** `−15%` of entry premium → close 100% of what remains. Checked
   first, always, so a time-based exit can never pre-empt the risk limit.
2. **Time-decay / consolidation stop** (both phases) → close 100%. Fires at the
   earlier of: 3 consecutive 10-min underlying candles inside a ±0.25% band, or
   an absolute **30-minute-in-trade** backstop.
3. **Trailing stop 6%** off the highest premium seen since entry → close 100%.
4. **Take-profit-1 `+25%`** → close **50%** of the original size, move the rest
   to Phase 2.

**Phase 2 — the runner (only after TP1).**

5. **Trailing stop 12%** off the highest premium seen since TP1 → close 100%.
6. **AI reversal exit** → close 100%. Fires on the first 10-min underlying bar
   where all three align: an engulfing candle against the position, wick > 50%
   of the bar range, and close through the 20-EMA against the position.

**Tunable parameters** (`simulate_hybrid_trade_exit` signature — defaults updated
2026-09-07):

| param | default | note |
|---|---|---|
| `hard_stop_pct` | 0.10 | was 0.15 |
| `trail_pct_phase1` | 0.06 | |
| `tp1_pct` | 0.30 | was 0.25 |
| `tp1_fraction` | 0.50 | unchanged |
| `trail_pct_phase2` | 0.12 | unchanged |
| `max_time_in_trade_minutes` | 30 | **see §4 — wrong for 2-week holds** |
| `consolidation_range_pct` | 0.005 | unchanged |

There is also a legacy model (`simulate_trade_exit`: flat 3% trailing stop OR
POC-reversal on the underlying) kept only as the "OLD" baseline in comparisons.

---

## 3. Per-strategy exit intent

| strategy | intended exit | in code? |
|---|---|---|
| **SMC** | hybrid model above (hard stop, TP1, trailing, reversal) | simulated only |
| **VWAP/DMI** | reference `stop = 2.5×ATR`, `target = 3× that` — *plus* the hybrid model's premium stop | reference numbers only; not enforced |
| **Pairs** | spread reverts to **z = 0** (target) / **z = ±3.5** (abandon). No premium stop on the package. | defined in scanner output, not managed |

---

## 4. Trading style — resolved 2026-09-07

All three strategies are **intraday**: enter on a minute-bar signal, take profit
or stop out **the same session**, never hold overnight. The 10–45 DTE
expiration is a **theta / pin cushion**, not a holding period — you buy time
value you don't intend to use, so a few hours of being early doesn't decay the
option or expose it to pin risk.

This makes the hybrid model in §2 **mostly the right shape** — it was built for
same-day scalps. What changes for the 2-week-cushion version:

- The **−15% → −10%** hard stop (Conservative).
- **TP1 +25% → +30%.**
- The **30-minute time backstop** was tuned for near-dated 0–2 DTE options where
  theta is brutal by lunch. With a 2-week contract there's no theta emergency —
  replace it with a **"dead trade" time stop** (flat, roughly ±8%, after
  ~90 min → close) plus a hard **end-of-day close**.
- Add an explicit **end-of-day flatten**: force-close everything ~15 min before
  the session close. This is what makes it "same day."
- The **3-candle / 10-min consolidation stop** and the **10-min reversal exit**
  stay — they're the right resolution for an intraday trade.

---

## 5. `exit_manager.py` — the live exit tier

The **Exit Monitor** scheduled task fires **every 5 minutes during market
hours**. `exit_manager.py` is a pure evaluator, no tool access, same discipline
as `live_prepare_order.py`: it **proposes** closes to `pending_exits.json`, it
does not place them.

### 5.1 Each cycle (the orchestrating task)

1. Pull open option positions (`get_option_positions`) and their live quotes
   (`get_option_quotes`); check open orders for a resting stop per position.
2. For a swing-thesis check (rules 3–4), re-run the entry detector on the
   underlying's recent candles and pass `thesis_broken` / `underlying_consolidating`.
3. Pass all of it to `exit_manager.py --positions-json ... --now-utc ...
   --session-close-utc ...`. It reconciles against `exit_state.json` (phase +
   post-TP1 peak) and `pending_exits.json` (the queue), evaluates the rules,
   writes any new close proposals, and prints tickets.
4. A position with an `awaiting_confirmation` proposal is not re-proposed
   unless a **higher-priority** rule now fires (then the old one is superseded).
   Stale proposals (> 45 min) are expired at the start of each run.

### 5.2 Exit rules — intraday, same-day close (`exit_manager.py`)

Evaluated every 5 min; **first match wins**, priority = table order. The
"close 100%" protective rules rank above the partial take-profit on purpose.

| # | rule | trigger | action |
|---|---|---|---|
| 1 | **Hard stop** | mark ≤ entry − **10%** (`HARD_STOP_PCT`) | close 100%; flags `NO RESTING STOP FOUND` if one isn't already placed |
| 2 | **End-of-day flatten** | within **15 min** (`EOD_FLATTEN_MIN`) of the session close, still open | close 100%, unconditionally — the "same day" guarantee |
| 3 | **Thesis break** | orchestrator sets `thesis_broken` (SMC opposite POC-retest · VWAP/DMI recrosses session VWAP against the position) | close 100% |
| 4 | **Consolidation** | orchestrator sets `underlying_consolidating` (3× 10-min candles inside ±0.25%) | close 100% |
| 5 | **Take-profit 1** | mark ≥ entry + **30%** (`TAKE_PROFIT_PCT`), pre-runner | close **50%** (whole 1-lot), move to runner phase, move stop on the rest to breakeven |
| 6 | **Runner trailing stop** | runner phase, mark ≤ **20%** (`RUNNER_TRAIL_PCT`) off its peak since TP1 | close remainder |
| 7 | **Dead-trade time stop** | ≥ **90 min** (`DEAD_TRADE_MIN`) in trade and \|P&L\| ≤ **8%** (`DEAD_TRADE_BAND`), pre-runner | close 100% — capital idle |

### 5.3 Pairs exits — `exit_manager.py → evaluate_pairs_exits()`

Orchestrator passes each open package's live `current_z`:
- `|z| ≤ 0.1` (`Z_EXIT_TARGET`) → close both legs (target hit)
- `|z| ≥ 3.5` (`Z_EXIT_ABANDON`) → close both legs (abandon)
- EOD flatten applies to the package too

No premium stop on the package.

### 5.4 Logging & reporting

`exit_manager.py` appends `exit_proposed` / `exit_expired` events to
`trade_log.jsonl`. Two renderers turn the log into docs:

- **`render_trade_log.py` → `TRADE_LOG.md`** — the raw event feed, newest first.
- **`reporting.py` → `RESULTS.md`** (PR 6) — the scorecard: realized P&L by
  window (from Robinhood's `get_realized_pnl`), win rate, a recent-trade ledger,
  the account snapshot, and a reconciliation line (trade-log realized total vs
  Robinhood's). The Market-Close task runs it and embeds the scorecard in its
  notification; `reporting.py --commit` pushes `RESULTS.md` to the repo from any
  push-enabled checkout so it is visible on GitHub.

---

## 6. Build order

| PR | contents | status |
|---|---|---|
| **1** | `docs/ENTRY_SPEC.md` + `docs/EXIT_SPEC.md` | ✅ merged (#2) |
| **2** | Risk dials + cutoff: hard stop `0.15→0.10`, loss guardrail `0.60→0.10`, drawdown `0.15→0.08`, `EXECUTION_CUTOFF 20:00→19:00`, take-profit ticket (+30%) added to proposals | ✅ merged (#3) |
| **3** | `vwap_dmi_screener.py` rebuilt — 5-min bars, session-anchored VWAP, warm-up seed (ENTRY_SPEC §2) | ✅ merged (#4) |
| **4** | Pairs rebuilt — daily cointegration tier writes `pairs_today.json`, intraday 5-min z-score trigger reads it (ENTRY_SPEC §3) | ✅ merged (#5) |
| **5** | `exit_manager.py` + new scheduled task — §5 rules, notify-and-confirm, 5-min cadence, all three strategies | ✅ merged (#6) |
| **6** | Reporting — `RESULTS.md` (win/loss/P&L vs Robinhood realized P&L) committed back to the repo each close | ✅ this PR |

Task-side (Chat, not this repo), in parallel: signal tasks → **15 min** cadence
(confirmed 2026-09-07); SMC task fetches 5-min bars; re-pin each task's commit
after every merge.
