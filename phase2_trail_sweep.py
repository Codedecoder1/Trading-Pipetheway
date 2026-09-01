"""
Trailing-stop parameter sweep on the SAME 30 synthetic contract paths built
for Phase 2 (Synthetic Underlying Replay). Re-runs
exit_engine.simulate_hybrid_trade_exit() via phase2_synthetic_replay.run_replay()
at trail_pct_phase1 in {0.05, 0.06, 0.07}, holding every other exit-engine
parameter fixed at production defaults (hard_stop_pct=0.15, tp1_pct=0.25,
tp1_fraction=0.5, trail_pct_phase2=0.12, 3-candle/30-min 0.5%-band
consolidation stop). This answers: does a tighter phase-1 trail (5%/6%) clip
winners before they run, or does it choke off drawdowns (like QCOM 7/29)
even faster than 7% did?

Same underlying/option price paths as the 7% baseline -- only the trail
threshold changes -- so any P&L difference is attributable purely to the
trail percentage, not to different market data.

DRY RUN / SIGNAL-ONLY: historical simulation only. No order-placement tool
is called.
"""
import json
from collections import Counter
from phase2_synthetic_replay import run_replay, setups

TRAIL_LEVELS = [0.05, 0.06, 0.07]

all_runs = {}
for trail in TRAIL_LEVELS:
    all_runs[trail] = run_replay(trail_pct_phase1=trail)

with open('/home/claude/smc_bot/diag/backtest/phase2_trail_sweep_results.json', 'w') as f:
    json.dump({str(t): r for t, r in all_runs.items()}, f, indent=2, default=str)

print("=== Trailing-stop sweep: 5% / 6% / 7% on the same 30 synthetic contracts ===\n")

print(f"{'trail':>6}  {'cat':>3}  {'n':>3}  {'win%':>6}  {'avg_pnl%':>9}  {'best%':>8}  {'worst%':>8}  "
      f"{'hard_stop_hits':>14}  {'tp1_hits':>8}")
for trail in TRAIL_LEVELS:
    results = all_runs[trail]
    for cat in ["ITM", "ATM", "OTM"]:
        rows = [r for r in results if r["category"] == cat]
        pnls = [r["pnl_pct"] for r in rows]
        wins = [p for p in pnls if p > 0]
        n = len(pnls)
        win_rate = 100.0 * len(wins) / n
        avg_pnl = sum(pnls) / n
        best = max(pnls)
        worst = min(pnls)
        hard_stops = sum(1 for r in rows for leg in r["legs"] if leg["reason"] == "HARD_STOP")
        tp1_hits = sum(1 for r in rows for leg in r["legs"] if leg["reason"] == "TAKE_PROFIT_1")
        print(f"{trail:>5.0%}  {cat:>3}  {n:>3}  {win_rate:>5.1f}%  {avg_pnl:>+8.2f}%  "
              f"{best:>+7.2f}%  {worst:>+7.2f}%  {hard_stops:>14}  {tp1_hits:>8}")
    # blended (all 30)
    results_all = results
    pnls = [r["pnl_pct"] for r in results_all]
    wins = [p for p in pnls if p > 0]
    n = len(pnls)
    hard_stops = sum(1 for r in results_all for leg in r["legs"] if leg["reason"] == "HARD_STOP")
    tp1_hits = sum(1 for r in results_all for leg in r["legs"] if leg["reason"] == "TAKE_PROFIT_1")
    print(f"{trail:>5.0%}  {'ALL':>3}  {n:>3}  {100*len(wins)/n:>5.1f}%  {sum(pnls)/n:>+8.2f}%  "
          f"{max(pnls):>+7.2f}%  {min(pnls):>+7.2f}%  {hard_stops:>14}  {tp1_hits:>8}")
    print()

print("--- QCOM 7/29 (the only losing setup at 7%) across trail levels ---")
for trail in TRAIL_LEVELS:
    results = all_runs[trail]
    for r in results:
        if r["symbol"] == "QCOM" and r["date"] == "2026-07-29":
            reasons = [(leg["fraction"], leg["reason"]) for leg in r["legs"]]
            print(f"  trail={trail:.0%}  {r['category']:3s}  pnl={r['pnl_pct']:+.2f}%  legs={reasons}")

print("\n--- Exit-reason mix, ALL 30 contracts, per trail level ---")
for trail in TRAIL_LEVELS:
    results = all_runs[trail]
    reason_counts = Counter()
    for r in results:
        for leg in r["legs"]:
            reason_counts[leg["reason"]] += 1
    print(f"  trail={trail:.0%}: {dict(reason_counts)}")
