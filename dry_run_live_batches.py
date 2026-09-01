"""
REVISION 15 (2026-08-30) helper -- prints <=10-symbol batches for THIS
cycle's live universe, the same output shape dry_run_universe.py used to
print for the old static list, so the rest of the live-trigger pipeline
(steps 5+) doesn't need to change how it reads batches.

Expects dry_run_live_universe.json (a JSON array of tickers -- the calling
session's run_scan results unioned with MAJOR_ETFS) to already exist in
this directory; the calling session writes that file itself, e.g.:

    python3 -c "import json; json.dump(sorted(set(SCAN_TICKERS) | set(MAJOR_ETFS_LIST)), open('dry_run_live_universe.json','w'))"

MAJOR_ETFS_LIST is importable from index_universe.py if convenient, but
does not have to be -- it's a fixed, short, hardcoded list either way:
["SPY","QQQ","IWM","DIA","XLF","XLE","XBI","SMH","TQQQ","SQQQ","SOXL","LABU"].

dry_run_check.py (REVISION 15) reads the same dry_run_live_universe.json
directly and re-derives the union with MAJOR_ETFS defensively -- this
script's only job is the batch-printing convenience for step 5's fetch loop.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_UNIVERSE_PATH = os.path.join(HERE, 'dry_run_live_universe.json')

BATCH = 10

if __name__ == "__main__":
    if not os.path.exists(LIVE_UNIVERSE_PATH):
        print(f"ERROR: {LIVE_UNIVERSE_PATH} not found. The calling session must run the "
              f"'SMC Bot - Live Movers Gate' scan (mcp__RBH__run_scan) and write its "
              f"result -- unioned with MAJOR_ETFS -- to this file BEFORE running this script.")
        sys.exit(1)

    with open(LIVE_UNIVERSE_PATH) as f:
        universe = sorted(set(json.load(f)))

    batches = [universe[i:i + BATCH] for i in range(0, len(universe), BATCH)]

    print(f"Universe size: {len(universe)} symbols, {len(batches)} batches of <=10")
    for i, b in enumerate(batches):
        print(f"{i}: {b}")
