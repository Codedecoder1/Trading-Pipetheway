"""
Consolidates raw get_equity_historicals JSON dumps (one file per batched
call, saved verbatim -- either the tool's inline JSON or the auto-saved
file it points to when the result is too large) into the two inputs
dry_run_check.py expects:

  dry_run_raw/daily/*.json    -> dryrun_prev_close.json  ({symbol: prev_close})
  dry_run_raw/intraday/*.json -> dryrun_today_bars.json  ({symbol: [bar, ...]}, TODAY's date only)

prev_close is taken as the close of the most recent COMPLETE daily bar
strictly before today's date (so a same-day partial daily bar, if the API
ever returns one, is never mistaken for the prior close).

Usage: python3 dry_run_consolidate.py YYYY-MM-DD   (today's date, UTC)
"""
import json, glob, sys, os

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
today = sys.argv[1] if len(sys.argv) > 1 else None
if not today:
    print("ERROR: pass today's date as YYYY-MM-DD (UTC)"); sys.exit(1)

def load_all(pattern):
    out = []
    for fp in sorted(glob.glob(pattern)):
        try:
            out.append(json.load(open(fp)))
        except Exception as ex:
            print(f"WARN: could not parse {fp}: {ex}")
    return out

# --- prev close from daily bars ---
prev_close = {}
daily_files = load_all(os.path.join(BACKTEST_DIR, 'dry_run_raw', 'daily', '*.json'))
print(f"daily files loaded: {len(daily_files)}")
for d in daily_files:
    for r in d.get('data', {}).get('results', []):
        sym = r['symbol']
        bars = [b for b in r.get('bars', []) if b['begins_at'][:10] < today]
        if not bars:
            continue
        bars.sort(key=lambda b: b['begins_at'])
        prev_close[sym] = float(bars[-1]['close_price'])

json.dump(prev_close, open(os.path.join(BACKTEST_DIR, 'dryrun_prev_close.json'), 'w'))
print(f"prev_close resolved for {len(prev_close)} symbols")

# --- today's intraday bars ---
today_bars = {}
intraday_files = load_all(os.path.join(BACKTEST_DIR, 'dry_run_raw', 'intraday', '*.json'))
print(f"intraday files loaded: {len(intraday_files)}")
for d in intraday_files:
    for r in d.get('data', {}).get('results', []):
        sym = r['symbol']
        bars = [b for b in r.get('bars', []) if b['begins_at'][:10] == today]
        if not bars:
            continue
        today_bars.setdefault(sym, [])
        today_bars[sym].extend(bars)

for sym in today_bars:
    today_bars[sym].sort(key=lambda b: b['begins_at'])

json.dump(today_bars, open(os.path.join(BACKTEST_DIR, 'dryrun_today_bars.json'), 'w'))
print(f"today's bars resolved for {len(today_bars)} symbols")

missing_prev = set(today_bars) - set(prev_close)
if missing_prev:
    print(f"WARN: {len(missing_prev)} symbols have today's bars but no prev_close: {sorted(missing_prev)}")
