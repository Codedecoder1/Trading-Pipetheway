# Exit Specification

Single source of truth for **how a position should be closed**. This is the
document to argue with before we build `exit_manager.py`.

Status: commit `c22641c` (2026-09-07) + the "Conservative" changes agreed
2026-09-07 (marked ▶ PENDING).

---

## 1. What actually happens today

**Exits are not managed by the pipeline.** The only exit artifact the pipeline
produces is a *planned* stop-loss ticket printed in the proposal notification:

| field | value |
|---|---|
| type | `stop_market` (stop loss) |
| trigger | `entry ask − 15%`, rounded to the cent |
| time in force | GTC |
| when placed | **by the human, by hand, after the entry fills** |

`compute_hard_stop_price()` computes the number. Nothing places it, nothing
watches it, nothing places a take-profit, and no task ever calls a closing
order. If you do not place the stop yourself, the position has no protection.

▶ **PENDING (Conservative):** planned stop trigger `−15% → −10%`
(`HARD_STOP_PCT 0.15 → 0.10`), and every proposal also carries a **take-profit
ticket**: sell **half** the position at **entry + 30%** (limit, GTC).

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

**Tunable parameters** (`simulate_hybrid_trade_exit` signature):

| param | value | ▶ PENDING (Conservative) |
|---|---|---|
| `hard_stop_pct` | 0.15 | **0.10** |
| `trail_pct_phase1` | 0.06 | unchanged |
| `tp1_pct` | 0.25 | **0.30** |
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

## 4. Why this model does not fit the current strategy

The hybrid model was built for **same-day scalps** on near-dated options. The
pipeline now buys **10–45 DTE** contracts meant to work over ~2–3 weeks
(`select_expiration.py`, EXECUTION_CUTOFF raised to the session close). Against
that horizon:

- The **30-minute time-decay backstop** force-closes almost every trade within
  the first hour. **Must be removed or raised to a multi-day value.**
- The **3-candle consolidation stop** (10-min candles) fires on any quiet hour —
  far too sensitive for a multi-day hold.
- **6% / 12% premium trailing stops** are tight for a 2–3 week option that
  swings intraday. Likely widen, or make them daily-bar based.
- The **AI reversal exit** on 10-min candles is intraday logic; on a swing hold
  it should read daily candles.

**Decision needed:** either (a) rework the exit model for a 2–3 week swing hold,
or (b) go back to near-dated options and same-day exits. This doc assumes (a).

---

## 5. Proposed spec for `exit_manager.py` (to build — notify-and-confirm)

A new scheduled task, firing **every 5 minutes during market hours**. Same
discipline as entries: it **proposes** closes, it does not place them.

### 5.1 Each cycle

1. Pull open option positions (`get_option_positions`) and their live quotes
   (`get_option_quotes`), plus today's realized P&L (`get_realized_pnl`).
2. Reconcile against `pending_live_orders.json` / `trade_log.jsonl` — know the
   entry price, entry time, and current planned stop for each position.
3. For each position, evaluate the exit rules (§5.2) and, if one triggers,
   write a **close proposal** to a `pending_exits.json` queue + notify.
4. Never propose the same close twice while one is awaiting confirmation.

### 5.2 Exit rules for a 2–3 week directional hold (▶ all PENDING review)

| rule | trigger | action |
|---|---|---|
| Hard stop | premium ≤ entry − **10%** | close 100% — this should already be a resting GTC order; the manager just alerts if it is missing |
| Take-profit 1 | premium ≥ entry + **30%** | close **50%**, raise stop on the rest to breakeven |
| Trailing (runner) | after TP1: premium falls **20%** off its post-TP1 peak (daily basis) | close remainder |
| Thesis break | SMC: opposite POC-retest fires · VWAP/DMI: close crosses back through VWAP-200 against the position | close 100% |
| Time stop | **8 calendar days** in trade with P&L between −10% and +15% | close 100% — do not ride theta into the last week |
| Expiry guard | **2 trading days** to expiration, still open | close 100% regardless |

### 5.3 Pairs exits (separate path)

Re-check the pair's live z-score each cycle. `|z| ≤ 0.1` → propose closing both
legs (target hit). `|z| ≥ 3.5` → propose closing both legs (abandon). No premium
stop.

### 5.4 Logging

Every evaluation writes a line to `trade_log.jsonl`
(`event: "exit_evaluated"` / `"exit_proposed"` / `"position_closed"`), and a
generated `RESULTS.md` (see the reporting PR) is committed back to the repo so
the record is visible on GitHub, not just in the task's cloud workspace.

---

## 6. Build order

1. This spec — agree on §4 (swing vs near-dated) and §5.2 numbers.
2. Risk-dial PR — the `▶ PENDING` constants in §1–2 and ENTRY_SPEC §4.
3. `exit_manager.py` + its scheduled task — §5, notify-and-confirm.
4. Reporting PR — `RESULTS.md`, win/loss/P&L, committed back to the repo.
