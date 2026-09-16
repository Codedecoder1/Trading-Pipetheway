# Daily Debit Spread Strategy — Setup & Scheduled Task

**Status:** Code ready | Awaiting task setup  
**Launch Date:** Tomorrow (first market open after setup)  
**Run Schedule:** Every 30 minutes, 7am–12pm Pacific (14:00–19:00 UTC)  
**DTE Range:** 30–60 days  
**Max Risk:** $50 per spread | 25% BP per spread | 1 active position at a time  

---

## What's Included

Three Python modules handle the full strategy:

1. **`debit_spread_filters.py`** — Gate 0 filters
   - Trend direction (price vs 200-VWAP + ADX > 20)
   - Earnings blackout (±10 days)
   - Volume gate (RVOL >= 1.5)

2. **`debit_spread_selector.py`** — Strike selection
   - Call spreads: ATM long (~0.50 delta) + OTM short (~0.35-0.40 delta)
   - Put spreads: ATM long (~-0.50 delta) + OTM short (~-0.35-0.40 delta)
   - Spread width: $1.00 (stocks < $100) or $2.50 (stocks >= $100)
   - Liquidity checks: bid-ask <= 10%, OI >= 500, min price >= $0.15

3. **`debit_spread_scanner.py`** — Orchestrator
   - Runs the full pipeline: fetch → filter → select → propose
   - Outputs proposals to `pending_live_orders.json` (bracket format)
   - Logs all signals to `trade_log.jsonl`

---

## Scheduled Task Prompt

**Task Name:** `Daily Debit Spread Scanner`  
**Cron:** `0,30 14-18 * * 1-5` (every 30 min, 14:00-18:00 UTC = 7am-11am Pacific)  
**Pinned Commit:** `85ebd3dbb3b5341febb34632a14f2c870da534a1` (or latest)

**Prompt (copy exactly below):**

```
Run the Daily Debit Spread scanner (Call & Put spreads, 30-60 DTE).

1. Get the stock universe:
   - Run: get_equity_historicals for the same universe as SMC Bot:
     * 12 major ETFs (SPY, QQQ, IWM, DIA, SMH, XLF, XLE, XBI, TQQQ, SQQQ, SOXL, LABU)
     * Plus live movers from: mcp__RBH__run_scan(scan_id="96f10af3-ee65-497b-9dcd-40ebdb84e83d")
   - Get 200+ bars (5-day lookback minimum) for each symbol
   - Output: store as {symbol: [bars]} for trend/volume analysis

2. Fetch earnings calendar:
   - Run: mcp__RBH__get_earnings_calendar
   - Extract report dates for all upcoming earnings
   - Use for earnings blackout check (±10 days)

3. Fetch option chains:
   - For each passing symbol (from Gate 0), get 30-60 DTE expirations
   - Fetch full option chain via get_option_chains / get_option_instruments
   - Store contracts by symbol

4. Get current account state:
   - get_portfolio (buying_power, total_equity)
   - This is used for position sizing

5. Run the scanner:
   - python3 debit_spread_scanner.py
   - This internally:
     a. Filters each symbol through Gate 0 (trend, earnings, volume)
     b. Selects Call & Put spreads for passing symbols
     c. Sizes positions (max $50 risk, 25% BP, max 1 open)
     d. Proposes spreads to pending_live_orders.json (bracket format)
     e. Logs all signals to trade_log.jsonl

6. Send me:
   - Any spreads proposed (symbol, direction, debit/profit, DTE)
   - Any signals rejected (symbol, reason)
   - Summary of this firing: "X call spreads, Y put spreads proposed"

7. STANDING RULE: No place_option_order, place_equity_order, or review_equity_order. Ever.
   This is signal-only. You review and confirm in the Robinhood app.

8. Bracket format when you confirm:
   - ENTRY: Buy the long leg, immediately sell the short leg (market or limit order)
   - STOP: Close if debit > 50% of initial net debit (half max risk)
   - TAKE-PROFIT: Close if spread value reaches 50-65% of max profit

All proposals go to pending_live_orders.json. You control execution manually.
```

---

## How to Set It Up

### Step 1: Create the Scheduled Task

**In your Claude Code backend:**

1. Go to **Scheduled Tasks**
2. Click **Create** or **New Task**
3. Fill in:
   - **Name:** `Daily Debit Spread Scanner`
   - **Schedule:** Cron `0,30 14-18 * * 1-5` 
     - (Every 30 min, 14:00-18:00 UTC = 7am-11am Pacific)
   - **Pinned Commit:** `85ebd3dbb3b5341febb34632a14f2c870da534a1`
   - **Prompt:** (paste the prompt from above)
4. **Save**

### Step 2: Verify Python Code

All three modules should already be in your repo:
- `debit_spread_filters.py` ✅
- `debit_spread_selector.py` ✅
- `debit_spread_scanner.py` ✅

Test locally (optional):
```bash
cd /home/user/Trading-Pipetheway
python3 -c "from debit_spread_filters import check_trend_gate; print('Imports OK')"
python3 -c "from debit_spread_selector import select_call_spread; print('Imports OK')"
python3 -c "python3 debit_spread_scanner.py"
```

### Step 3: Test the Task

**Manually fire the task** from your Claude Code backend:
1. Go to **Scheduled Tasks**
2. Find **Daily Debit Spread Scanner**
3. Click **Run** or **Test** or **Fire Now**
4. Wait ~1-2 minutes for it to complete
5. Check the output:
   - Should list symbols scanned
   - Should show "PROPOSED:" lines if any spreads were found
   - Should show any rejections (trend, earnings, volume)

### Step 4: Verify Outputs

Once the task runs, check:
- **`pending_live_orders.json`** — Should have new proposals with `"strategy": "debit_spread"`
- **`diag/backtest/trade_log.jsonl`** — Should have new `"event_type": "debit_spread_candidate"` entries

---

## Key Differences from Other Strategies

| Aspect | SMC/VWAP/Pairs | Debit Spread |
|--------|---------|--------------|
| **Instruments** | Single-leg options (calls/puts) | 2-leg spreads (call/put pairs) |
| **DTE** | 2 weeks (~10-45 days) | 4-8 weeks (30-60 days) |
| **Entry** | Automatic, bracket ready | Automatic, bracket ready |
| **Position Limit** | Flexible, dynamic | Max 1 active spread at a time |
| **Exit Targets** | % max profit + % loss | Dynamic % max profit + 50% loss stop |
| **Run Frequency** | Every 30 min (market hours) | Every 30 min (7am-12pm Pacific) |

---

## Exit Management

**When to close:**
1. **Take-Profit:** Spread reaches 50-65% of max profit → Close both legs
2. **Stop-Loss:** Spread loses 50% of initial net debit → Close both legs
3. **Expiration:** 7-10 days before DTE → Close to avoid final-week decay
4. **Manual:** You can close anytime in the app

**How to close:**
- Sell-to-close the long leg (buy it back at lower price)
- Buy-to-close the short leg (sell it back at higher price)
- **Or** use a single "close spread" order in Robinhood (if available)

---

## Testing Checklist

- [ ] All 3 Python modules created and in repo
- [ ] Scheduled task created in Claude Code backend
- [ ] Cron set to `0,30 14-18 * * 1-5` (7am-11am Pacific)
- [ ] Prompt copied exactly from above
- [ ] Pinned commit set to latest
- [ ] Manual test firing successful
- [ ] Proposals appear in `pending_live_orders.json`
- [ ] Signals logged in `trade_log.jsonl`
- [ ] Notifications enabled on your phone (fixed yesterday)

---

## Live Launch Checklist

Before going live tomorrow:

- [ ] Task has run at least once successfully
- [ ] You've reviewed at least 1 proposed spread
- [ ] You understand the bracket entry (long leg + short leg)
- [ ] You know how to confirm/reject in the app
- [ ] You know how to close spreads early (TP/SL)
- [ ] Position size is comfortable ($50 max risk per spread)
- [ ] Account is funded and ready to trade

---

## Questions?

Refer to:
- `debit_spread_filters.py` — Filter logic & constants
- `debit_spread_selector.py` — Strike selection & liquidity rules
- `debit_spread_scanner.py` — Main orchestrator & proposal format
- This document — Setup & task configuration

**Ready to deploy and start scanning tomorrow!** 🚀
