"""
Consolidates raw get_equity_historicals JSON dumps (one file per batched
call, same "data.results[].symbol/bars" shape dry_run_consolidate.py and
vwap_dmi_screener.py's own internal loader both already consume) staged in
pairs_raw/*.json into the single {symbol: [bar, ...]} dict
pairs_arb_scanner.py's __main__ block expects (it takes a bars_path
positional arg, unlike SMC/VWAP which re-scan a raw directory at run time --
this script exists to bridge that difference, not to add new logic).

Usage: python3 pairs_consolidate.py   (no date arg needed -- unlike
dry_run_consolidate.py, this keeps the full multi-day history the
correlation/cointegration windows need, it doesn't split out "today only")
"""
import json, glob, os

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
RAW_DIR = os.path.join(BACKTEST_DIR, 'pairs_raw')
OUT_PATH = os.path.join(BACKTEST_DIR, 'pairs_hourly_bars.json')

bars_by_symbol = {}
files = sorted(glob.glob(os.path.join(RAW_DIR, '*.json')))
print(f"raw files found: {len(files)}")
for fp in files:
    try:
        d = json.load(open(fp))
    except Exception as ex:
        print(f"WARN: could not parse {fp}: {ex}")
        continue
    for r in d.get('data', {}).get('results', []):
        sym = r.get('symbol')
        bars = r.get('bars', [])
        if not sym or not bars:
            continue
        bars_by_symbol.setdefault(sym, [])
        bars_by_symbol[sym].extend(bars)

for sym in bars_by_symbol:
    bars_by_symbol[sym].sort(key=lambda b: b['begins_at'])
    # de-dupe on begins_at in case a symbol appeared in more than one batch file
    seen = set()
    deduped = []
    for b in bars_by_symbol[sym]:
        if b['begins_at'] in seen:
            continue
        seen.add(b['begins_at'])
        deduped.append(b)
    bars_by_symbol[sym] = deduped

json.dump(bars_by_symbol, open(OUT_PATH, 'w'))
print(f"consolidated bars for {len(bars_by_symbol)} symbols -> {OUT_PATH}")
