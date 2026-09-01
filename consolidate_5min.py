import json, os
from collections import defaultdict

toolresults_dir = "/root/.claude/projects/-home-claude/ac405b5d-200a-5fe3-9ebf-7a49638773ee/tool-results/"
inline_dir = "/home/claude/smc_bot/diag/backtest/inline_fetches/"

# The 13 original Stage B files (dates 07-27 through 08-19, excluding the 8 missing ones)
stage_b_files = [
    "mcp-RBH-get_equity_historicals-1787702251401.txt",  # 07-27
    "mcp-RBH-get_equity_historicals-1787702252459.txt",  # 07-28
    "mcp-RBH-get_equity_historicals-1787702254659.txt",  # 07-29
    "mcp-RBH-get_equity_historicals-1787702255675.txt",  # 07-30 part1
    "mcp-RBH-get_equity_historicals-1787702256994.txt",  # 07-30 part2
    "mcp-RBH-get_equity_historicals-1787702258580.txt",  # 07-31
    "mcp-RBH-get_equity_historicals-1787702258950.txt",  # 08-03
    "mcp-RBH-get_equity_historicals-1787702260047.txt",  # 08-04
    "mcp-RBH-get_equity_historicals-1787702261236.txt",  # 08-05
    "mcp-RBH-get_equity_historicals-1787702264454.txt",  # 08-10
    "toolu_01NiH1fvLmVUfBdhLiE5VJwa.txt",                 # 08-13
    "mcp-RBH-get_equity_historicals-1787702269376.txt",  # 08-17
    "mcp-RBH-get_equity_historicals-1787702270415.txt",  # 08-18
    "mcp-RBH-get_equity_historicals-1787702271465.txt",  # 08-19
]

# The 6 newly re-fetched (extended bounds, overflowed to file) missing-date files
refetch_files = [
    "mcp-RBH-get_equity_historicals-1787702706507.txt",  # 08-07 BKNG,QCOM
    "mcp-RBH-get_equity_historicals-1787702710482.txt",  # 08-11 GOOGL,HON
    "mcp-RBH-get_equity_historicals-1787702712005.txt",  # 08-12 HD,META,NVDA
    "mcp-RBH-get_equity_historicals-1787702712441.txt",  # 08-14 AVGO,INTU
    "mcp-RBH-get_equity_historicals-1787702714128.txt",  # 08-20 BA,ISRG,WMT
    "mcp-RBH-get_equity_historicals-1787702715215.txt",  # 08-24 MA,V
    "mcp-RBH-get_equity_historicals-1787702809917.txt",  # 07-28 REGN,SHW
]

# manually-saved inline files
inline_files = [
    "2026-08-06.json",  # BA,TMUS
    "2026-08-21.json",  # GS
]

# symbol -> date -> list of bars (session=='reg' only)
data = defaultdict(lambda: defaultdict(list))

def ingest_results(results):
    for r in results:
        sym = r["symbol"]
        for b in r["bars"]:
            if b.get("session") != "reg":
                continue
            date = b["begins_at"][:10]
            data[sym][date].append(b)

for fn in stage_b_files + refetch_files:
    path = os.path.join(toolresults_dir, fn)
    with open(path) as f:
        raw = json.load(f)
    ingest_results(raw["data"]["results"])

for fn in inline_files:
    path = os.path.join(inline_dir, fn)
    with open(path) as f:
        raw = json.load(f)
    ingest_results(raw["results"])

# sort bars by time within each symbol/date
for sym in data:
    for date in data[sym]:
        data[sym][date].sort(key=lambda b: b["begins_at"])

# Load the narrowed mover events to verify coverage
with open("/home/claude/smc_bot/diag/backtest/mover_events_narrowed.json") as f:
    events = json.load(f)

missing = []
counts = {}
for e in events:
    sym, date = e["symbol"], e["date"]
    n = len(data.get(sym, {}).get(date, []))
    counts[(sym,date)] = n
    if n == 0:
        missing.append((sym, date))

print(f"Total mover events: {len(events)}")
print(f"Events with intraday data: {sum(1 for v in counts.values() if v>0)}")
print(f"Missing: {len(missing)}")
if missing:
    for m in missing[:30]:
        print("  MISSING:", m)

# bar count sanity check (should be ~78-79 for full regular session)
low_count = [(k,v) for k,v in counts.items() if 0 < v < 70]
print(f"Low-bar-count events (<70 bars, possible partial data): {len(low_count)}")
for k,v in low_count[:20]:
    print("  LOW:", k, v)

out = {sym: dict(dates) for sym, dates in data.items()}
with open("/home/claude/smc_bot/diag/backtest/narrowed_5min_bars.json", "w") as f:
    json.dump(out, f)

total_bars = sum(len(bars) for dates in data.values() for bars in dates.values())
print(f"\nSaved narrowed_5min_bars.json: {len(data)} symbols, {total_bars} total bars")
