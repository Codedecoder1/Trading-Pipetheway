# Exit Specification

Single source of truth for **how a position should be closed**. This is the
document to argue with before we build `exit_manager.py`.

Status: current through the "risk dials" PR (2026-09-07). §5
(`exit_manager.py`) is still to build — that is PR 5.

---

## 1. What actually happens today

**Exits are not managed by the pipeline yet** (that is PR 5, `exit_manager.py`).
As of the "risk dials" PR (2026-09-07), every proposal notification prints two
*planned* tickets the human places by hand after the entry fills:

| ticket | type | trigger / limit | TIF |
|---|---|---|---|
| Stop-loss | `stop_market` | `entry ask − 10%`, rounded to the cent | GTC |
| Take-profit | `limit` | `entry ask + 30%` | GTC |

`compute_hard_stop_price()` / `compute_take_profit_price()` compute the numbers
(`HARD_STOP_PCT = 0.10`, `TAKE_PROFIT_PCT = 0.30`). On a ≥2-lot the take-profit
sells half and keeps a runner; on a 1-lot it closes the whole position. Nothing
places or watches these until PR 5 — if you do not place the stop yourself, the
position has no protection.

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

### 5.2 Exit rules — intraday, same-day close (▶ all PENDING review)

Evaluated every 5 min against the live option premium and the underlying.

| # | rule | trigger | action |
|---|---|---|---|
| 1 | **Hard stop** | premium ≤ entry − **10%** | close 100%. Should also be a resting GTC stop-market placed at entry; the manager alerts if it's missing. |
| 2 | **End-of-day flatten** | **15 min before session close**, still open | close 100%, unconditionally. This is the "same day" guarantee. |
| 3 | **Take-profit 1** | premium ≥ entry + **30%** | close **50%**, move stop on the rest to breakeven (entry). |
| 4 | **Runner trailing stop** | after TP1: premium falls **20%** off its highest point since TP1 | close remainder |
| 5 | **Dead-trade time stop** | ~**90 min** in trade and premium within **±8%** of entry | close 100% — capital isn't working, free it up |
| 6 | **Thesis break** | SMC: opposite POC-retest fires · VWAP/DMI: close crosses back through the VWAP-200 against the position | close 100% |
| 7 | **Consolidation stop** | 3 consecutive 10-min underlying candles inside a ±0.25% band | close 100% |

No overnight holds, ever — rule 2 covers the case where nothing else fired.

### 5.3 Pairs exits (separate path)

Re-check the pair's live z-score each cycle:
- `|z| ≤ 0.1` → propose closing both legs (target hit).
- `|z| ≥ 3.5` → propose closing both legs (abandon).
- **End-of-day flatten** (rule 2 above) applies to the package too — close both
  legs 15 min before the close if still open.

No premium stop on the package.

### 5.4 Logging

Every evaluation writes a line to `trade_log.jsonl`
(`event: "exit_evaluated"` / `"exit_proposed"` / `"position_closed"`), and a
generated `RESULTS.md` (see the reporting PR) is committed back to the repo so
the record is visible on GitHub, not just in the task's cloud workspace.

---

## 6. Build order

| PR | contents | status |
|---|---|---|
| **1** | `docs/ENTRY_SPEC.md` + `docs/EXIT_SPEC.md` | ✅ merged (#2) |
| **2** | Risk dials + cutoff: hard stop `0.15→0.10`, loss guardrail `0.60→0.10`, drawdown `0.15→0.08`, `EXECUTION_CUTOFF 20:00→19:00`, take-profit ticket (+30%) added to proposals | ✅ this PR |
| **3** | `vwap_dmi_screener.py` rebuilt — 5-min bars, session-anchored VWAP, warm-up seed (ENTRY_SPEC §2) | next |
| **4** | Pairs rebuilt — daily cointegration tier writes `pairs_today.json`, intraday 5-min z-score trigger reads it (ENTRY_SPEC §3) | after 3 |
| **5** | `exit_manager.py` + new scheduled task — §5 rules, notify-and-confirm, 5-min cadence, all three strategies | after 3–4 |
| **6** | Reporting — `RESULTS.md` (win/loss/P&L vs Robinhood realized P&L) committed back to the repo each close | last |

Task-side (Chat, not this repo), in parallel: signal tasks → **15 min** cadence
(confirmed 2026-09-07); SMC task fetches 5-min bars; re-pin each task's commit
after every merge.
