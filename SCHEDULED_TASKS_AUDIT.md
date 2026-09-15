# Scheduled Tasks Audit & Fix Guide

**Generated:** 2026-09-15  
**Status:** COMPREHENSIVE AUDIT + FIX INSTRUCTIONS  
**Action Required:** Complete task setup/updates in Claude Code backend

---

## Executive Summary

Your Trading-Pipetheway has **11 scheduled tasks** that need to be set up or updated. The key changes:
- **Repin all tasks** to the latest commit on `main`
- **Delete excess siblings** (keep only 2 per task, not 4 or 12)
- **Update prompts** for new features (bracket orders, better exits, 5-min bars)
- **Create NEW Exit Monitor task** (critical for stop/target management)
- **All strategies run 5 days/week** (Mon–Fri, no day-of-week splits)

---

## Task Audit Table

| # | Task Name | Cron (UTC) | Siblings | Status | Notes |
|---|-----------|-----------|----------|--------|-------|
| 1 | SMC Bot Live Signal Monitor `:00` | `0 14-18 * * 1-5` | 2 | NEEDS REPIN | Update prompt for bracket orders |
| 2 | SMC Bot Live Signal Monitor `:30` | `30 13-18 * * 1-5` | ✓ | NEEDS REPIN | Identical to `:00` |
| 3 | VWAP/DMI Signal Monitor `:00` | `0 14-18 * * 1-5` | 2 | NEEDS REPIN | Add 5-min bar fetch |
| 4 | VWAP/DMI Signal Monitor `:30` | `30 13-18 * * 1-5` | ✓ | NEEDS REPIN | Identical to `:00` |
| 5 | Pairs Stat-Arb Signal Monitor `:00` | `0 14-18 * * 1-5` | 2 | NEEDS REPIN | Self-contained mode |
| 6 | Pairs Stat-Arb Signal Monitor `:30` | `30 13-18 * * 1-5` | ✓ | NEEDS REPIN | Identical to `:00` |
| 7 | Exit Monitor `:00` | `0 14-20 * * 1-5` | 2 | **NEW** | Critical new task |
| 8 | Exit Monitor `:30` | `30 13-19 * * 1-5` | ✓ | **NEW** | Sibling of `:00` |
| 9 | Daily Market-Open Health Check | `32 13 * * 1-5` | — | UNCHANGED | Pairs only (no daily-tier) |
| 10 | 10:05am Progress Recap | `5 17 * * 1-5` | — | UNCHANGED | Info only |
| 11 | Market-Close Daily Summary | `5 20 * * 1-5` | — | NEEDS UPDATE | Now runs `reporting.py` |

**Key totals:**
- 6 signal-monitor tasks (3 strategies × 2 siblings each)
- 2 exit-monitor tasks (NEW)
- 3 admin/reporting tasks
- **Total: 11 tasks**

---

## Fix Order (Do These in Sequence)

### Phase 1: Delete Excess Siblings (DO FIRST)

Check your Claude Code backend for tasks with extra siblings. Delete any beyond this list:

**Keep only these:**
- SMC Bot Live Signal Monitor `:00` (one)
- SMC Bot Live Signal Monitor `:30` (one)
- VWAP/DMI Signal Monitor `:00` (one)
- VWAP/DMI Signal Monitor `:30` (one)
- Pairs Stat-Arb Signal Monitor `:00` (one)
- Pairs Stat-Arb Signal Monitor `:30` (one)

**Delete any of these if they exist:**
- Old SMC Wed-only task
- Old VWAP/DMI Wed-only task (superseded, now runs all 5 days)
- Old Pairs Thu-only task (superseded, now runs all 5 days)
- Any SMC, VWAP, or Pairs task beyond the 2 per strategy listed above

---

### Phase 2: Repin All Existing Tasks

Each task must be pinned to the latest commit on `main`. Get the latest commit hash:

```bash
cd /home/user/Trading-Pipetheway
git fetch origin main
git rev-parse origin/main
```

Then for **each existing task** in your backend, update the pinned commit to that hash.

---

### Phase 3: Update Task Prompts

Replace each task's prompt with the ones below.

---

## Updated Task Prompts

### Task 1–2: SMC Bot Live Signal Monitor (`:00` and `:30`)

**Prompt (identical for both):**

```
Run the SMC signal-only pipeline, 2-week bracket entry, every 30 min.

1. Run: python3 dry_run_check.py
   - This reads the live scanner result (or falls back to index_universe.py)
   - Outputs signals to diag/backtest/dry_run_live_signal_detect.json

2. For each signal, run: python3 resolve_expiration.py
   - Pick the first expiration ~2 weeks out (10–45 calendar days)
   - Fetch the contract chain and select an ATM-or-OTM contract

3. Run: python3 live_prepare_order.py
   - Inputs: the contract + signal (from dry_run_live_signal_detect.json)
   - This prints a **3-order bracket**:
     * Primary: BUY the call/put
     * Stop: −10% mark, stop-market, GTC, quantity same as buy
     * Take-Profit: +30% mark, limit, GTC, quantity same as buy
   - Output: appends to pending_live_orders.json, awaiting_confirmation = true
   - NEVER calls place_option_order (you confirm manually in the Robinhood app)

4. Send me:
   - Any signals detected (symbol, pattern, price, time)
   - Any proposals in pending_live_orders.json (the 3-order bracket)
   - Any rejected proposals (reason, e.g., guardrail, budget, risk gate)
   - Summary of what happened this firing

5. STANDING RULE: No place_option_order, place_equity_order, or review_equity_order calls. Ever.
```

---

### Task 3–4: VWAP/DMI Signal Monitor (`:00` and `:30`)

**Prompt (identical for both):**

```
Run the VWAP/DMI strategy: fetch 5-min bars, detect trend, propose 2-week bracket entry.

1. Stage 5-minute historical bars:
   - Run: get_equity_historicals(interval="5minute")
   - Symbols: the 24-symbol watchlist from vwap_dmi_screener.py (AMD, NVDA, AAPL, PLTR, MSFT, TSLA, AMZN, GOOGL, COIN, SOFI, HOOD, MARA, ROKU, PYPL, F, GM, SPY, QQQ, IWM, XLF, XLE, SMH, TQQQ, SQQQ)
   - Prior session + today (~80 bars/symbol)
   - Output to: vwap_dmi_raw/<batch>.json
   - Shape: {"data":{"results":[{"symbol":"...","bars":[{open_price,high_price,low_price,close_price,volume,begins_at},...]}]}}

2. Run: python3 vwap_dmi_screener.py
   - Detects: close crossing 200-bar VWAP + DMI alignment + ADX(14) > 20
   - Output: diag/backtest/dry_run_live_signal_detect.json

3. For each signal, run: python3 resolve_expiration.py
   - Pick the first expiration ~2 weeks out (10–45 calendar days)
   - Fetch the contract chain and select an ATM-or-OTM contract

4. Run: python3 live_prepare_order.py
   - Inputs: the contract + signal
   - This prints a **3-order bracket**:
     * Primary: BUY the call/put
     * Stop: −10% mark, stop-market, GTC
     * Take-Profit: +30% mark, limit, GTC
   - Output: appends to pending_live_orders.json, awaiting_confirmation = true
   - NEVER calls place_option_order

5. Send me:
   - Any signals detected (symbol, VWAP cross, DMI/ADX, price, time)
   - Any proposals (the 3-order bracket)
   - Any rejected proposals (reason)
   - Summary of this firing

6. STANDING RULE: No place_option_order, place_equity_order, or review_equity_order calls. Ever.
```

---

### Task 5–6: Pairs Stat-Arb Signal Monitor (`:00` and `:30`)

**Prompt (identical for both):**

```
Run the Pairs stat-arb strategy: self-contained, one firing does everything.

Self-contained mode: git push doesn't work from the task container, so this task runs entirely offline—fetch bars, detect pairs, run the scanner, propose entries, all in one firing. No cross-firing state, no git commits.

1. Read pairs_universe.json (~65 curated symbols)

2. Stage 5-minute historical bars:
   - Run: get_equity_historicals(interval="5minute")
   - Symbols: those from pairs_universe.json
   - Depth: ~8 sessions deep (≥ ~450 bars/symbol)
   - Output to: pairs_5min_bars.json
   - Shape: {symbol:[{close_price,begins_at,...},...]}

3. Run: python3 pairs_arb_scanner.py pairs_5min_bars.json --self-contained
   - Runs the correlation → cointegration → z-score funnel each time
   - Any pair that decouples drops out automatically (no state persistence)
   - Outputs signals to diag/backtest/dry_run_pairs_signal_detect.json

4. For each signal, run: python3 resolve_pairs_leg.py (×2), then python3 pairs_prepare_order.py
   - Pick expirations, select contracts (one per leg)
   - Output: appends to pending_live_orders.json, awaiting_confirmation = true
   - This is a 2-leg entry (long leg_a, short leg_b), not a bracket on a single symbol

5. Send me:
   - Any pairs detected (leg_a, leg_b, z-score, correlation, price, time)
   - Any proposals (both legs, prices, time)
   - Any rejected proposals (reason)
   - Summary of this firing

6. STANDING RULE: No place_option_order, place_equity_order, or review_equity_order calls. Ever.
```

---

### Task 7–8: Exit Monitor (`:00` and `:30`) — **NEW**

**Prompt (identical for both):**

```
Run the Exit Manager: stateless position monitoring and exit signal generation, every 30 min.

This task monitors open positions and applies exit logic. It generates **signals only**—no order placement, just reporting.

1. Fetch current positions:
   - get_option_positions (nonzero only)
   - get_option_orders (all recent)
   - Agentic account

   If no open option positions, STOP.

2. Build position dict for each open position:
   - Fields: see exit_manager.py docstring
   - Booleans from order history:
     * has_resting_stop: an open stop-market SELL exists for this option
     * has_resting_tp: an open limit SELL exists for this option
     * has_pending_close: any other working SELL on this option
     * tp1_filled: a partial close SELL has already filled
     * quantity: CURRENTLY OPEN contract count
   - Prices from get_option_quotes (current_bid, current_ask, current_mark)

3. Optional: thesis check (re-run entry detector on fresh 5-min bars, set thesis_broken / underlying_consolidating)

4. For any open pairs package, build:
   {pair, current_z, leg_a{...}, leg_b{...}, has_pending_close}

5. Run: python3 exit_manager.py --positions-json '[...]' --pairs-json '[...]' --now-utc <ISO> --session-close-utc <today>T20:00:00Z
   - This is fully stateless (no exit_state.json, no persistence)
   - Outputs suggested exit signals (close, scale, exit-thesis-broken, etc.)

6. Send me every ticket it prints:
   - Current position status
   - Exit signals (if any)
   - Next action (if any)

7. **CRITICAL RULE: Place nothing. This is signals only. You review and act manually.**

8. STANDING RULE: No place_option_order, place_equity_order, or review_equity_order calls. Ever.
```

---

### Task 9: Daily Market-Open Health Check

**Status: UNCHANGED**

```
One firing, Mon–Fri at 13:32 UTC (6:32am Pacific, ~28 min before market open).

1. Check Robinhood account status (portfolio, buying power, margin)
2. Verify the account is properly connected and tradeable
3. Log account state to diag/backtest/daily_health_check.json
4. Send summary: "Account ready for market open. Buying power: $X. Positions: Y."

If anything is wrong (account locked, not enough buying power, connection failed), escalate in the notification.
```

---

### Task 10: 10:05am Progress Recap

**Status: UNCHANGED**

```
One firing, Mon–Fri at 17:05 UTC (10:05am Pacific, ~1hr 35min after market open).

1. Check current open positions and orders from Robinhood
2. Read pending_live_orders.json (any awaiting_confirmation entries)
3. Summarize: "X signal(s) detected so far today. Y proposal(s) awaiting confirmation. Z position(s) currently open."
4. If there are proposals awaiting confirmation, remind the user to review and place the order bracket in the app.
```

---

### Task 11: Market-Close Daily Summary

**Status: NEEDS UPDATE** — now runs `reporting.py`

```
One firing, Mon–Fri at 20:05 UTC (1:05pm Pacific, market close).

1. Fetch realized P&L from Robinhood:
   - get_realized_pnl(span="day")
   - Output: --realized-json

2. Fetch closed trade history:
   - get_pnl_trade_history
   - Output: --closed-trades-json
   - Compute win_rate (if applicable)

3. Fetch current account snapshot:
   - get_portfolio (account equity, buying_power, etc.)
   - get_option_positions (any remaining open positions)
   - get_option_quotes (current prices)
   - Output: --account-json

4. Run: python3 reporting.py \
     --now-utc <ISO> \
     --realized-json '...' \
     --closed-trades-json '...' \
     --account-json '...'
   - Generates a scorecard with today's P&L, trade summary, position status

5. Send the scorecard as the notification body:
   - Today's P&L (realized + unrealized)
   - Trade summary (count, win rate, avg size)
   - Open positions (qty, mark, P&L)
   - Account status (equity, buying power)

KNOWN LIMITATION: Task container cannot push to GitHub. Either:
   - Skip GitHub RESULTS.md update, rely on the notification scorecard, or
   - Run reporting.py manually from an interactive checkout after market close

Log all output to diag/backtest/daily_summary.json for reference.
```

---

## Python Code Changes Required

### 1. **Bracket Order Format** (ALREADY NEEDED)

`live_prepare_order.py` must print a 3-order proposal:
- **Primary:** BUY the contract
- **Stop:** −10% mark, stop-market, GTC, same quantity
- **Take-Profit:** +30% mark, limit, GTC, same quantity

**Status:** Check if this is already implemented. If not, update the output format.

### 2. **5-Minute Bars for VWAP/DMI & Pairs** (CRITICAL)

Both tasks need to fetch with `interval="5minute"`, not hourly.

**File:** `vwap_dmi_screener.py`  
**Check:** Verify it reads from `vwap_dmi_raw/<batch>.json` (5-min bars), not hourly.

**File:** `pairs_arb_scanner.py`  
**Check:** Verify it reads from `pairs_5min_bars.json` (5-min bars), not hourly.

### 3. **Exit Manager** (CRITICAL NEW CODE)

**File:** `exit_manager.py`  
**Status:** Should already exist (mentioned in SCHEDULED_TASK_UPDATES.md).  
**Check:**
- Takes `--positions-json`, `--pairs-json`, `--now-utc`, `--session-close-utc`
- Returns stateless exit signals (no `exit_state.json`)
- Does NOT call `place_option_order`

### 4. **Reporting with Scorecard** (CRITICAL NEW)

**File:** `reporting.py`  
**Status:** Mentioned in SCHEDULED_TASK_UPDATES.md as needing implementation.  
**Required Parameters:**
- `--now-utc <ISO>` — current timestamp
- `--realized-json '<json>'` — P&L data from Robinhood
- `--closed-trades-json '<json>'` — trade history
- `--account-json '<json>'` — portfolio snapshot

**Output:** Scorecard with:
- Today's realized/unrealized P&L
- Trade count, win rate, avg size
- Open positions (qty, mark, P&L)
- Account health (equity, buying power)

---

## Implementation Checklist

### ✅ Pre-Setup (Do First)

- [ ] Get latest commit on `main`: `git fetch origin main && git rev-parse origin/main`
- [ ] Delete any excess task siblings (keep only 2 per strategy)
- [ ] Document the pinned commit hash for re-pinning all tasks

### ✅ Code Validation (Do Second)

- [ ] Check `live_prepare_order.py` outputs 3-order bracket
- [ ] Check `vwap_dmi_screener.py` reads 5-min bars (not hourly)
- [ ] Check `pairs_arb_scanner.py` reads 5-min bars (not hourly)
- [ ] Verify `exit_manager.py` exists and is stateless
- [ ] Verify `reporting.py` exists and outputs scorecard

### ✅ Task Setup (Do Third — in Claude Code backend)

**For each existing task:**
1. Update prompt to the one listed above
2. Update pinned commit to latest on `main`
3. Save changes

**New tasks to create:**
1. Exit Monitor `:00` — cron `0 14-20 * * 1-5`
2. Exit Monitor `:30` — cron `30 13-19 * * 1-5`

**Existing tasks to verify/update:**
- SMC Bot Live Signal Monitor `:00` & `:30`
- VWAP/DMI Signal Monitor `:00` & `:30`
- Pairs Stat-Arb Signal Monitor `:00` & `:30`
- Daily Market-Open Health Check
- 10:05am Progress Recap
- Market-Close Daily Summary

---

## Testing After Setup

Once all tasks are updated/created:

1. **Manual trigger test** — Fire one SMC and one Pairs task manually to verify the new prompts work
2. **Check outputs:**
   - Signals in `diag/backtest/dry_run_live_signal_detect.json`
   - Proposals in `pending_live_orders.json` (3-order bracket format)
   - Exit signals from Exit Monitor
3. **Dry-run mode** — Keep all tasks enabled but verify against live data before enabling order placement

---

## Summary

| Phase | Action | Status |
|-------|--------|--------|
| 1 | Delete excess siblings | **Do first** |
| 2 | Get latest commit hash | **Do second** |
| 3 | Repin all existing tasks | **Do third** |
| 4 | Update all task prompts | **Do fourth** |
| 5 | Create Exit Monitor tasks | **Do fifth** |
| 6 | Validate Python code | **Verify as needed** |
| 7 | Test one task firing | **Validate setup** |

Once complete, all 11 tasks will be synchronized, using the latest code, with correct 5-day schedules and new bracket/exit logic.
