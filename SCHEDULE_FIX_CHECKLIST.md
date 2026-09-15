# Schedule Fix Quick Checklist

**TL;DR** — Fix all 11 scheduled tasks in ~30 minutes.

---

## 🚀 Quick Start (Copy-Paste Order)

### 1️⃣ Get the magic hash (2 min)

```bash
cd /home/user/Trading-Pipetheway
git fetch origin main
git rev-parse origin/main
```

**Copy this hash** → You'll need it 5 times below.

---

### 2️⃣ Go to Claude Code Backend

Open your Claude Code dashboard/settings and navigate to **Scheduled Tasks**.

---

### 3️⃣ Delete Old Tasks (2 min)

Delete ANY task that is NOT in this list:

✅ **KEEP THESE 11:**
1. SMC Bot Live Signal Monitor `:00`
2. SMC Bot Live Signal Monitor `:30`
3. VWAP/DMI Signal Monitor `:00`
4. VWAP/DMI Signal Monitor `:30`
5. Pairs Stat-Arb Signal Monitor `:00`
6. Pairs Stat-Arb Signal Monitor `:30`
7. Exit Monitor `:00` (may not exist — create if missing)
8. Exit Monitor `:30` (may not exist — create if missing)
9. Daily Market-Open Health Check
10. 10:05am Progress Recap
11. Market-Close Daily Summary

❌ **DELETE THESE (if they exist):**
- Anything with "Wed-only" or "Thu-only" in the name
- Old SMC task (if >2 SMC tasks exist)
- Old VWAP task (if >2 VWAP tasks exist)
- Old Pairs task (if >2 Pairs tasks exist)
- Any test/sandbox tasks

---

### 4️⃣ Repin All 9 Existing Tasks (10 min)

For each of these 9 tasks:

```
- SMC Bot Live Signal Monitor :00
- SMC Bot Live Signal Monitor :30
- VWAP/DMI Signal Monitor :00
- VWAP/DMI Signal Monitor :30
- Pairs Stat-Arb Signal Monitor :00
- Pairs Stat-Arb Signal Monitor :30
- Daily Market-Open Health Check
- 10:05am Progress Recap
- Market-Close Daily Summary
```

**For each task:**
1. Click into it
2. Find **"Pinned commit"** or **"Revision"** field
3. Paste the hash from step 1
4. Click **Save**

---

### 5️⃣ Update Signal Monitor Prompts (10 min)

Open `SCHEDULED_TASKS_AUDIT.md` in this repo.

**Task 1–2: SMC Bot Live Signal Monitor (`:00` and `:30`)**
- Find section "Task 1–2: SMC Bot Live Signal Monitor"
- Copy the prompt
- Paste into **both** `:00` and `:30` tasks
- Save each

**Task 3–4: VWAP/DMI Signal Monitor (`:00` and `:30`)**
- Find section "Task 3–4: VWAP/DMI Signal Monitor"
- Copy the prompt
- Paste into **both** `:00` and `:30` tasks
- Save each

**Task 5–6: Pairs Stat-Arb Signal Monitor (`:00` and `:30`)**
- Find section "Task 5–6: Pairs Stat-Arb Signal Monitor"
- Copy the prompt
- Paste into **both** `:00` and `:30` tasks
- Save each

**Task 7–8: Exit Monitor (`:00` and `:30`)**
- Find section "Task 7–8: Exit Monitor (NEW)"
- Copy the prompt
- If tasks don't exist, **CREATE them** (see step 6)
- Paste into **both** `:00` and `:30` tasks
- Save each

---

### 6️⃣ Create Exit Monitor Tasks (If Missing) (5 min)

If Exit Monitor `:00` and `:30` don't exist, create them:

**Exit Monitor `:00`**
- Name: `Exit Monitor :00`
- Cron: `0 14-20 * * 1-5`
- Pinned commit: `<hash from step 1>`
- Prompt: (copy from `SCHEDULED_TASKS_AUDIT.md`)
- Create

**Exit Monitor `:30`**
- Name: `Exit Monitor :30`
- Cron: `30 13-19 * * 1-5`
- Pinned commit: `<hash from step 1>`
- Prompt: (copy from `SCHEDULED_TASKS_AUDIT.md`)
- Create

---

### 7️⃣ Update Market-Close Task (1 min)

**Market-Close Daily Summary** — just verify/update the prompt:
- Find section "Task 11: Market-Close Daily Summary" in `SCHEDULED_TASKS_AUDIT.md`
- Update the prompt to mention `reporting.py`
- Save

---

### 8️⃣ Test One Task (2 min)

Back in Claude Code backend:

1. **Manually trigger** "SMC Bot Live Signal Monitor `:00`"
2. Wait ~30 seconds
3. Check output:
   - Should print "SIGNAL:" + symbol info, or "No signals"
   - Should NOT error out
4. If OK ✅ → All tasks are ready

---

## 📋 Verification

- [ ] Hash copied from `git rev-parse origin/main`
- [ ] Deleted excess task siblings
- [ ] Repinned 9 existing tasks to new hash
- [ ] Updated prompts for 6 signal-monitor tasks
- [ ] Created/updated Exit Monitor tasks (2)
- [ ] Updated Market-Close task prompt
- [ ] Tested SMC Bot task (no errors)

**All done!** ✅

---

## 📚 Reference Documents

Full details in:
- `SCHEDULED_TASKS_AUDIT.md` — Complete audit + all prompts
- `IMPLEMENTATION_GUIDE.md` — Step-by-step guide + validation results
- `SCHEDULED_TASK_UPDATES.md` — Original requirements (from 2026-09-07)

---

## 🆘 If Something's Wrong

| Problem | Solution |
|---------|----------|
| Task won't fire | Check cron syntax ends in `1-5` (Mon–Fri) |
| Bracket not in pending_live_orders.json | Check signal actually fired; check task stdout |
| Exit Monitor errors | Verify position dict format (see `exit_manager.py` docstring) |
| Can't find pinned commit field | Look for "Revision", "Commit", or "Git hash" in task settings |

---

**Status:** All 11 tasks ready to go live after backend setup. 🚀
