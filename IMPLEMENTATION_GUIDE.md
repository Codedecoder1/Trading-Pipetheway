# Scheduled Tasks Implementation Guide

**Generated:** 2026-09-15  
**Status:** READY TO IMPLEMENT  
**Estimated Time:** 1–2 hours

---

## ✅ Code Validation Results

All Python code is **VALIDATED AND READY**:

### ✅ 1. Bracket Order System (VERIFIED)

**File:** `live_prepare_order.py` (lines 157-250)  
**Status:** ✅ **COMPLETE**

The system already outputs a 3-order bracket:
1. **Entry:** BUY 1 contract at ask price (limit order)
2. **Stop-Loss:** SELL 1 contract at -10% (stop-market, GTC)
3. **Take-Profit:** SELL portion at +30% (limit, GTC)

**Percentages:**
- `HARD_STOP_PCT = 0.10` → -10% stop (from `live_risk_checks.py:165`)
- `TAKE_PROFIT_PCT = 0.30` → +30% TP (from `live_risk_checks.py:253`)

**Output format:** Prints human-readable bracket + appends to `pending_live_orders.json`:
```json
{
  "order_id": "<uuid>",
  "symbol": "AAPL",
  "direction": "call",
  "quantity": 1,
  "planned_hard_stop_price": <price>,
  "planned_take_profit_price": <price>,
  "status": "awaiting_confirmation"
}
```

### ✅ 2. Exit Manager (VERIFIED)

**File:** `exit_manager.py` (lines 1-71)  
**Status:** ✅ **COMPLETE**

Stateless exit evaluator. Takes positions + quotes, prints exit signals, places nothing.

**Usage:**
```bash
python3 exit_manager.py \
  --positions-json '[{position_id, symbol, strike, expiration, ...}]' \
  --pairs-json '[{pair, current_z, leg_a, leg_b, ...}]' \
  --now-utc 2026-09-15T18:05:00Z \
  --session-close-utc 2026-09-15T20:00:00Z
```

**Outputs:** Exit signal proposals (no orders placed).

### ✅ 3. Reporting (VERIFIED)

**File:** `reporting.py` (lines 1-80)  
**Status:** ✅ **COMPLETE**

Pure scorecard renderer. Takes Robinhood data, generates report.

**Usage:**
```bash
python3 reporting.py \
  --now-utc 2026-09-15T20:05:00Z \
  --realized-json '{"today":..,"win_rate":..}' \
  --closed-trades-json '[{"symbol","exit_price","realized_pnl",...}]' \
  --account-json '{"total_value","buying_power",...}'
```

**Outputs:** RESULTS.md scorecard (no git push from task container).

### ✅ 4. 5-Minute Bar Fetching (VERIFIED)

**VWAP/DMI:** `vwap_dmi_screener.py` — reads from `vwap_dmi_raw/<batch>.json`  
**Pairs:** `pairs_arb_scanner.py` — reads from `pairs_5min_bars.json`

Both expect 5-minute bars. Orchestrating task must fetch with `interval="5minute"`.

---

## Step-by-Step Implementation

### STEP 1: Get Latest Commit Hash

```bash
cd /home/user/Trading-Pipetheway
git fetch origin main
LATEST_COMMIT=$(git rev-parse origin/main)
echo "Latest commit: $LATEST_COMMIT"
```

**Save this value** — you'll need it to repin all tasks.

---

### STEP 2: Verify No Uncommitted Changes

```bash
git status
```

If clean, proceed. If not, commit or stash before repinning tasks.

---

### STEP 3: Delete Excess Task Siblings (In Claude Code Backend)

Go to your Claude Code backend and **delete** any tasks beyond these 11:

**Keep:**
1. SMC Bot Live Signal Monitor `:00`
2. SMC Bot Live Signal Monitor `:30`
3. VWAP/DMI Signal Monitor `:00`
4. VWAP/DMI Signal Monitor `:30`
5. Pairs Stat-Arb Signal Monitor `:00`
6. Pairs Stat-Arb Signal Monitor `:30`
7. Exit Monitor `:00` (if exists; create if not)
8. Exit Monitor `:30` (if exists; create if not)
9. Daily Market-Open Health Check
10. 10:05am Progress Recap
11. Market-Close Daily Summary

**Delete:**
- Any old Wed-only or Thu-only tasks (superseded)
- Any task with >2 siblings for a single strategy
- Any test/sandbox tasks

---

### STEP 4: Repin All 11 Tasks (In Claude Code Backend)

For **each existing task**, update the pinned commit to the hash from Step 1.

**For each task:**
1. Open task settings
2. Find "Pinned commit" or "Revision"
3. Set to: `<hash from Step 1>`
4. Save

**Tasks to repin:**
- [ ] SMC Bot Live Signal Monitor `:00`
- [ ] SMC Bot Live Signal Monitor `:30`
- [ ] VWAP/DMI Signal Monitor `:00`
- [ ] VWAP/DMI Signal Monitor `:30`
- [ ] Pairs Stat-Arb Signal Monitor `:00`
- [ ] Pairs Stat-Arb Signal Monitor `:30`
- [ ] Daily Market-Open Health Check
- [ ] 10:05am Progress Recap
- [ ] Market-Close Daily Summary

---

### STEP 5: Update Task Prompts (In Claude Code Backend)

For **each signal-monitor task** (6 tasks), replace the prompt with the one from `SCHEDULED_TASKS_AUDIT.md`.

**Checklist:**

**SMC Bot Live Signal Monitor `:00` & `:30`:**
- [ ] Copy prompt from `SCHEDULED_TASKS_AUDIT.md` (Task 1–2 section)
- [ ] Paste into both tasks (identical prompt)
- [ ] Save

**VWAP/DMI Signal Monitor `:00` & `:30`:**
- [ ] Copy prompt from `SCHEDULED_TASKS_AUDIT.md` (Task 3–4 section)
- [ ] Paste into both tasks (identical prompt)
- [ ] Save

**Pairs Stat-Arb Signal Monitor `:00` & `:30`:**
- [ ] Copy prompt from `SCHEDULED_TASKS_AUDIT.md` (Task 5–6 section)
- [ ] Paste into both tasks (identical prompt)
- [ ] Save

**Exit Monitor `:00` & `:30`:**
- [ ] Copy prompt from `SCHEDULED_TASKS_AUDIT.md` (Task 7–8 section)
- [ ] Paste into both tasks (identical prompt)
- [ ] Save

**Admin/Reporting tasks:**
- [ ] Daily Market-Open Health Check — no change (UNCHANGED)
- [ ] 10:05am Progress Recap — no change (UNCHANGED)
- [ ] Market-Close Daily Summary — update for `reporting.py` (see audit)

---

### STEP 6: Create Exit Monitor Tasks (In Claude Code Backend)

If they don't already exist, **create 2 new tasks:**

**Task 1: Exit Monitor `:00`**
- **Name:** `Exit Monitor :00`
- **Cron:** `0 14-20 * * 1-5` (every day at 14:00–20:00 UTC, every hour)
- **Pinned commit:** Use the hash from Step 1
- **Prompt:** Copy from `SCHEDULED_TASKS_AUDIT.md` (Task 7–8 section)

**Task 2: Exit Monitor `:30`**
- **Name:** `Exit Monitor :30`
- **Cron:** `30 13-19 * * 1-5` (every day at 13:30–19:30 UTC, every hour)
- **Pinned commit:** Use the hash from Step 1
- **Prompt:** Identical to Exit Monitor `:00`

---

### STEP 7: Commit Changes to Git (Optional, But Recommended)

Update the SCHEDULED_TASK_UPDATES.md with any notes about the implementation:

```bash
cd /home/user/Trading-Pipetheway
git add SCHEDULED_TASKS_AUDIT.md IMPLEMENTATION_GUIDE.md
git commit -m "docs: scheduled tasks audit and implementation guide (2026-09-15)

- Generated comprehensive audit of all 11 scheduled tasks
- Validated bracket order system (-10% stop, +30% TP)
- Validated exit manager (stateless position monitoring)
- Validated reporting (scorecard generation)
- Created step-by-step implementation guide
- All code is ready; only backend task setup/updates needed"

git push -u origin claude/funny-meitner-k0yrrw
```

---

### STEP 8: Test One Task Firing (After Backend Updates)

Once all tasks are set up/updated in the backend:

**Test SMC Bot Live Signal Monitor:**
1. Manually trigger the `:00` firing from your Claude Code backend
2. Wait ~30 seconds for it to complete
3. Check the output:
   - Look for signals in terminal output
   - Verify `pending_live_orders.json` format (3-order bracket)
   - Check notification text includes bracket instructions

**Test Exit Monitor:**
1. Manually trigger the `:00` firing
2. Check output:
   - Should list any open positions
   - Print exit signal proposals (if any)
   - Should print "PROPOSED_EXITS: <n>"

**Test Reporting:**
1. Manually trigger Market-Close Daily Summary
2. Check output:
   - Should generate scorecard
   - Should print P&L, trade summary, account status

---

## Verification Checklist

### Pre-Implementation

- [ ] Got latest commit hash from `git rev-parse origin/main`
- [ ] Reviewed `SCHEDULED_TASKS_AUDIT.md` (11 tasks table)
- [ ] Reviewed Python code validation (all 3 ✅)

### During Implementation (Backend)

- [ ] Deleted excess task siblings (kept only 2 per strategy)
- [ ] Repinned all 9 existing tasks to latest commit
- [ ] Updated prompts for 6 signal-monitor tasks
- [ ] Updated prompt for Market-Close Daily Summary
- [ ] Created 2 Exit Monitor tasks (`:00` and `:30`)

### Post-Implementation (Testing)

- [ ] Manually fired SMC Bot (check output + pending_live_orders.json)
- [ ] Manually fired Exit Monitor (check signals)
- [ ] Manually fired Market-Close task (check scorecard)
- [ ] All 3 fired without errors ✅

### After First Live Day

- [ ] Market-open health check ran and reported
- [ ] At least one signal was detected (SMC, VWAP, or Pairs)
- [ ] Proposal bracket was generated correctly
- [ ] Exit Monitor ran on schedule
- [ ] Market-close summary was generated with scorecard

---

## Troubleshooting

### Task Doesn't Fire

**Check:**
1. Is the cron expression valid? (Should end in `* * 1-5` for Mon–Fri)
2. Is the pinned commit valid? (Check `git cat-file -t <hash>`)
3. Is the prompt correctly pasted (no truncation)?
4. Are there any syntax errors in the prompt?

### Bracket Not Appearing in pending_live_orders.json

**Check:**
1. Did the signal actually fire? (Check `dry_run_live_signal_detect.json`)
2. Did `live_prepare_order.py` run? (Check terminal output for "PREPARED:")
3. Is `pending_live_orders.json` writable? (Check file permissions)

### Exit Monitor Not Generating Signals

**Check:**
1. Are there actually open positions? (Check `get_option_positions`)
2. Is the position dict format correct? (Check against `exit_manager.py` docstring)
3. Are dates/times in ISO format? (Should be `2026-09-15T18:05:00Z`)

---

## Key Dates

- **Updated:** 2026-09-15
- **All code validated:** 2026-09-15
- **Ready for task backend setup:** 2026-09-15
- **Target go-live:** After task setup + first day of testing

---

## Questions?

Refer to:
- `SCHEDULED_TASK_UPDATES.md` — the source requirements
- `SCHEDULED_TASKS_AUDIT.md` — complete audit + prompts
- `bot_runbook.md` — architectural overview
- Python file docstrings — implementation details

Good luck! 🚀
