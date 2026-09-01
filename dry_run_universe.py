"""
Prints the production dry-run universe (Dow/S&P/Nasdaq/Russell/SOX/KBW/
S&P-500-top-200/MAJOR_ETFS static universe), chunked into batches of <=10
symbols (the get_equity_historicals per-call cap), one Python list literal
per line -- for the calling session to copy directly into its
mcp__RBH__get_equity_historicals symbols= argument, one call per batch.

CHRONIC_MOVERS (2026-08-28, per explicit user request): previously
excluded from the scan -- AMAT, LRCX, AMD, MU, ADBE, CRM, ORCL, TSLA --
for "chronically whipsawing" (noisier, more false-signal-prone than the
rest of the universe). The user explicitly asked to re-include all 8, so
the set below is now empty and kept only as a record of that history /
in case this ever needs reverting. If signal quality on these 8 names
looks noticeably worse than the rest of the universe once live, that's
the original rationale reasserting itself -- worth flagging back to the
user rather than silently re-excluding them.
"""
import sys
sys.path.insert(0, '/home/claude/smc_bot')
from index_universe import get_universe

CHRONIC_MOVERS = set()  # was {"AMAT", "LRCX", "AMD", "MU", "ADBE", "CRM", "ORCL", "TSLA"}
UNIVERSE = sorted(set(get_universe(dedup=True)) - CHRONIC_MOVERS)

BATCH = 10
batches = [UNIVERSE[i:i + BATCH] for i in range(0, len(UNIVERSE), BATCH)]

print(f"Universe size: {len(UNIVERSE)} symbols, {len(batches)} batches of <=10")
for i, b in enumerate(batches):
    print(f"{i}: {b}")
