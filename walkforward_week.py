"""
Walk-forward backtest harness for the "run the whole week and show what the
live SMC trigger would have found" request (2026-08-30). The live trigger
fires every 30 minutes, 13:30-19:30 UTC, and each firing only sees bars
available AS OF that moment -- evaluating a full day's bars in one shot
(dry_run_check.py's normal invocation) only checks the state at the LAST
bar, which is not equivalent. This script re-runs dry_run_check.evaluate()
once per simulated cycle, truncating each symbol's intraday bars to
<= the cycle timestamp, so it reproduces what each of the day's ~7 live
firings would actually have seen.

For each day it also applies the same "only act on the FIRST Layer-1
signal, then treat further signals that day as blocked by a pending order"
rule the live trigger prompt uses (steps 7-8 in both trigger prompts) --
one simulated proposal per day, in this dry-run signal-only sense (no
options data was fetched historically, so this reports the STOCK-level
signal only, not a resolved contract).

Usage: python3 walkforward_week.py <prev_close.json> <today_bars.json> <day_label>
"""
import json, sys, os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '/home/claude/smc_bot')
import dry_run_check as drc
from contract_filters import EXECUTION_CUTOFF

prev_close_path, today_bars_path, day_label = sys.argv[1], sys.argv[2], sys.argv[3]

with open(prev_close_path) as f:
    prev_close_by_symbol = json.load(f)
with open(today_bars_path) as f:
    full_bars_by_symbol = json.load(f)

# Determine the date from the data itself (first bar's date)
any_bars = next(iter(full_bars_by_symbol.values()))
date_str = any_bars[0]['begins_at'][:10]

cycle_times = [f"{date_str}T{h:02d}:30:00Z" for h in range(13, 20)]  # 13:30 .. 19:30 UTC

print(f"=== WALK-FORWARD {day_label} ({date_str}) -- {len(cycle_times)} simulated cycles, "
      f"universe {len(drc.UNIVERSE)} symbols, {len(full_bars_by_symbol)} with data ===")

all_signals_this_day = []
first_actionable = None  # first Layer-1 signal of the day (the one that would actually be acted on)
pending_from_ts = None

for cyc in cycle_times:
    cyc_dt = datetime.strptime(cyc, "%Y-%m-%dT%H:%M:%SZ")
    truncated = {}
    for sym, bars in full_bars_by_symbol.items():
        keep = [b for b in bars if b['begins_at'] <= cyc]
        if keep:
            truncated[sym] = keep

    hits = drc.evaluate(prev_close_by_symbol, truncated, now_ts=None)
    for h in hits:
        h['cycle'] = cyc
    if hits:
        for h in hits:
            key = (h['symbol'], h['direction'], h['timestamp'])
            if not any(s['symbol'] == h['symbol'] and s['direction'] == h['direction'] and s['timestamp'] == h['timestamp'] for s in all_signals_this_day):
                all_signals_this_day.append(h)
                print(f"  [{cyc}] NEW signal: {h['symbol']:6s} {h['direction']:4s} [{h['config']}/{h['interval']}] "
                      f"entry={h['entry_price']:.2f} mover={h['mover_pct']:+.2f}% signal_ts={h['timestamp']}")
                if first_actionable is None and pending_from_ts is None:
                    first_actionable = h
                    pending_from_ts = cyc

if not all_signals_this_day:
    print("  No Layer-1-passing signals at any cycle this day.")
else:
    print(f"\n  {len(all_signals_this_day)} distinct signal(s) detected across the day.")
    if first_actionable:
        sig_dt = datetime.strptime(first_actionable['timestamp'][:19], "%Y-%m-%d %H:%M:%S")
        cutoff_h, cutoff_m, cutoff_s = [int(x) for x in EXECUTION_CUTOFF.split(":")]
        cutoff_dt = sig_dt.replace(hour=cutoff_h, minute=cutoff_m, second=cutoff_s)
        past_cutoff = sig_dt > cutoff_dt
        print(f"  FIRST actionable signal (what the live bot would have proposed, since only the "
              f"first signal per day is acted on): {first_actionable['symbol']} {first_actionable['direction']} "
              f"[{first_actionable['config']}/{first_actionable['interval']}] entry={first_actionable['entry_price']:.2f} "
              f"mover={first_actionable['mover_pct']:+.2f}% signal_ts={first_actionable['timestamp']}")
        print(f"  Execution cutoff check ({EXECUTION_CUTOFF} UTC): "
              f"{'SIGNAL_ONLY -- fired after cutoff, would NOT have been auto-prepared' if past_cutoff else 'within cutoff -- WOULD have proceeded to contract resolution'}")

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'walkforward_{day_label}.json')
json.dump({"date": date_str, "signals": all_signals_this_day, "first_actionable": first_actionable}, open(out_path, 'w'), indent=2)
print(f"\n  Saved to {out_path}")
