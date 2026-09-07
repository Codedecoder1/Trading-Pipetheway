# Exit Specification

Single source of truth for **how a position should be closed**.

Status: intraday rebuild complete (PRs 1–6), then reworked to be **stateless**
(PR 7, 2026-09-07) after confirming scheduled firings share no filesystem.

---

## 1. The bracket — how every entry is protected

Every **entry** proposal from `live_prepare_order.py` prints a **3-order
bracket**. At confirmation the human (or an interactive session) places all
three — the buy first, the two resting orders right after it fills:

| # | ticket | type | price | TIF |
|---|---|---|---|---|
| 1 | Entry | limit BUY to open | `entry ask` | day |
| 2 | Stop-loss | `stop_market` SELL to close | `entry − 10%`, to the cent | GTC |
| 3 | Take-profit | `limit` SELL to close | `entry + 30%` | GTC |

`compute_hard_stop_price()` / `compute_take_profit_price()`
(`HARD_STOP_PCT = 0.10`, `TAKE_PROFIT_PCT = 0.30`). On a ≥2-lot the take-profit
sells half and keeps a runner; on a 1-lot it closes the whole position.

**Why a bracket:** with the stop and take-profit *resting at the broker*, the
two time-critical exits happen on their own. That is what lets the Exit Monitor
task run at 30-minute cadence instead of needing minute-by-minute coverage. If
you skip the resting orders, the position is unprotected between Exit Monitor
passes.

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

## 5. `exit_manager.py` — the live exit tier (stateless)

The **Exit Monitor** task fires ~every 30 min (2 offset hourly siblings).
`exit_manager.py` is a pure evaluator — no tool access, **no state file**. Phase
and de-duplication are reconstructed from the broker account each run, because
firings share nothing. It **prints** close tickets; it places nothing.

### 5.1 Each cycle (the orchestrating task)

1. `get_option_positions` + `get_option_orders` (recent) for the account.
2. Per position, build the dict in `exit_manager.py`'s docstring. From the order
   history derive: `has_resting_stop`, `has_resting_tp`, `has_pending_close`,
   `tp1_filled` (a partial close SELL already filled → runner phase), and the
   currently-open `quantity`. Quotes → `current_bid/ask/mark`.
3. Optional thesis check: re-run the entry detector on recent 5-min candles →
   `thesis_broken` / `underlying_consolidating`.
4. Run `exit_manager.py --positions-json … --pairs-json … --now-utc …
   --session-close-utc …`. Send every printed ticket. Place nothing.

### 5.2 Exit rules (`exit_manager.py`)

**First match wins**, priority = table order. Rules 1 and 5 fire **only when the
corresponding resting bracket order is missing** — when the bracket is in place
the broker handles the stop and the take-profit, and a duplicate proposal would
be noise. `has_pending_close` suppresses any proposal for that position.

| # | rule | trigger | action |
|---|---|---|---|
| 1 | **Stop unprotected** | mark ≤ entry − **10%** (`HARD_STOP_PCT`) **and no resting stop** | close 100% now; place resting stops on the rest |
| 2 | **End-of-day flatten** | within **15 min** (`EOD_FLATTEN_MIN`) of the close, open | close 100%, unconditional |
| 3 | **Thesis break** | orchestrator set `thesis_broken` | close 100% |
| 4 | **Consolidation** | orchestrator set `underlying_consolidating` | close 100% |
| 5 | **Take-profit 1** | mark ≥ entry + **30%** (`TAKE_PROFIT_PCT`), not `tp1_filled`, **no resting take-profit** | close 50% (whole 1-lot); move the stop on the rest to breakeven |
| 6 | **Runner give-back** | `tp1_filled` and mark ≤ entry (round-tripped to breakeven) | close the remainder |
| 7 | **Dead-trade time stop** | ≥ **90 min** (`DEAD_TRADE_MIN`) in trade and \|P&L\| ≤ **8%** (`DEAD_TRADE_BAND`), not `tp1_filled` | close 100% — capital idle |

Rule 6 replaces the old peak-tracking runner trail — a trailing stop needs a
remembered peak, which a stateless run can't have. "Give back everything you
made past the first profit" is the stateless equivalent.

### 5.3 Pairs exits — `evaluate_pairs_exits()`

Orchestrator passes each open package's live `current_z` and `has_pending_close`:
- `|z| ≤ 0.1` (`Z_EXIT_TARGET`) → close both legs (target hit)
- `|z| ≥ 3.5` (`Z_EXIT_ABANDON`) → close both legs (abandon)
- EOD flatten applies too

No premium stop on the package.

### 5.4 Logging & reporting

`trade_log.jsonl` is **per-firing only** — it does not survive a container
teardown, so it is not a history. It gives that firing's own output/notification
context and nothing more.

The durable record is **`RESULTS.md`**, built by `reporting.py` from
**Robinhood's own** realized P&L / order history — the broker is the source of
truth. Scorecard: realized P&L by window (`get_realized_pnl`), win rate, recent
closed-trade ledger, account snapshot. The Market-Close task runs it and embeds
the scorecard in its notification; `reporting.py --commit` (and
`pairs_daily_tier.py --commit`) push to the repo — but only from a push-enabled
checkout, which the task container may or may not be (see
`SCHEDULED_TASK_UPDATES.md` §G).

---

## 6. Build order

| PR | contents | status |
|---|---|---|
| **1** | `docs/ENTRY_SPEC.md` + `docs/EXIT_SPEC.md` | ✅ merged (#2) |
| **2** | Risk dials + cutoff: hard stop `0.15→0.10`, loss guardrail `0.60→0.10`, drawdown `0.15→0.08`, `EXECUTION_CUTOFF 20:00→19:00`, take-profit ticket (+30%) added to proposals | ✅ merged (#3) |
| **3** | `vwap_dmi_screener.py` rebuilt — 5-min bars, session-anchored VWAP, warm-up seed (ENTRY_SPEC §2) | ✅ merged (#4) |
| **4** | Pairs rebuilt — daily cointegration tier writes `pairs_today.json`, intraday 5-min z-score trigger reads it (ENTRY_SPEC §3) | ✅ merged (#5) |
| **5** | `exit_manager.py` + new scheduled task — §5 rules, notify-and-confirm, 5-min cadence, all three strategies | ✅ merged (#6) |
| **6** | Reporting — `RESULTS.md` (win/loss/P&L vs Robinhood realized P&L) committed back to the repo each close | ✅ merged (#7) |
| **7** | **Stateless / no-shared-filesystem rework** — `exit_manager.py` drops all state files and reconstructs phase/dedup from broker orders; entry proposal becomes a 3-order **bracket**; `pairs_today.json` committed to the repo for the cross-firing handoff; `trade_log` demoted to per-firing, `reporting.py` on Robinhood only | ✅ this PR |

Task-side (Chat, not this repo), in parallel: signal tasks → **15 min** cadence
(confirmed 2026-09-07); SMC task fetches 5-min bars; re-pin each task's commit
after every merge.
