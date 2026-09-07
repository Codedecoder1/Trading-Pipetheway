"""
Pairs stat-arb -- DAILY TIER (2026-09-07, INTRADAY REBUILD, per explicit
user request). See docs/ENTRY_SPEC.md section 3.

WHY THIS EXISTS: cointegration on 5-minute noise is statistically weak. So
the strategy is split in two:

  * DAILY TIER (this file) -- runs ONCE near the open (piggy-backs on the
    Market-Open Health Check task). Correlation pre-filter + single-lag
    Dickey-Fuller cointegration on HOURLY bars over ~60-90 sessions -- the
    same long-horizon test the old all-in-one scanner used. Output: the
    day's tradeable pairs, each with a FIXED hedge ratio, written to
    pairs_today.json.

  * INTRADAY TIER (pairs_arb_scanner.py) -- runs every 15 min. Reads
    pairs_today.json, computes each pair's spread with the day's fixed
    hedge ratio and a rolling z-score over 60 x 5-minute bars, and triggers
    an entry at |z| >= 2.0. No cointegration re-check -- the pair already
    qualified this morning.

SIGNAL-ONLY discipline is unchanged: this file calls no broker/order tool.
It only reads staged historicals and writes pairs_today.json.

Usage:
  python3 pairs_daily_tier.py <hourly_bars.json> [--session-date YYYY-MM-DD]

<hourly_bars.json> is {symbol: [ {close_price, begins_at, ...}, ... ]},
the same shape pairs_arb_scanner.py already consumes.
"""
import json, os, sys
from datetime import datetime, timezone, date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairs_arb_scanner import (
    load_universe, _load_series, discover_candidate_pairs, check_cointegration,
    COINT_P_MAX, CORR_WINDOW, CORR_THRESHOLD, Z_WINDOW, Z_ENTRY,
)

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
PAIRS_TODAY_FILE = os.path.join(BACKTEST_DIR, "pairs_today.json")

# The daily-tier cointegration test wants a long history. If fewer than this
# many aligned hourly bars are available for a pair, skip it -- do not trade
# a pair we could not properly test this morning.
MIN_HOURLY_BARS = 250


def build_pairs_today(bars_by_symbol: dict, universe: list = None,
                       session_date: str = None, candidates: list = None) -> dict:
    """Runs the correlation + cointegration funnel on hourly bars and returns
    the pairs_today payload (also what gets written to pairs_today.json).

    candidates: optional explicit list of (ticker_a, ticker_b) tuples to
    test. When omitted, the correlation pre-filter runs over `universe`
    (or the small fallback list if the universe is tiny, e.g. a dry run).
    """
    universe = universe or load_universe()
    universe = [s for s in universe if s in bars_by_symbol] or list(bars_by_symbol.keys())

    if candidates is None:
        if len(universe) > 20:
            candidates = discover_candidate_pairs(bars_by_symbol, universe)
        else:
            candidates = discover_candidate_pairs(
                bars_by_symbol, universe, corr_threshold=CORR_THRESHOLD)
            if not candidates:
                from pairs_arb_scanner import FALLBACK_WATCHLIST_PAIRS
                candidates = FALLBACK_WATCHLIST_PAIRS

    qualified = []
    for ticker_a, ticker_b in candidates:
        sa = _load_series(bars_by_symbol, ticker_a)
        sb = _load_series(bars_by_symbol, ticker_b)
        df = pd.concat([sa, sb], axis=1, join="inner").dropna()
        if len(df) < MIN_HOURLY_BARS:
            continue
        series_a, series_b = df[ticker_a], df[ticker_b]
        p_value, hedge_ratio, adf_t = check_cointegration(series_a.values, series_b.values)
        if p_value >= COINT_P_MAX:
            continue
        abs_corr = float(series_a.corr(series_b))
        qualified.append({
            "pair": f"{ticker_a}/{ticker_b}",
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "hedge_ratio": round(float(hedge_ratio), 6),
            "adf_p_value": round(float(p_value), 4),
            "adf_t_stat": round(float(adf_t), 3),
            "abs_corr": round(abs(abs_corr), 4),
            "hourly_bars_used": int(len(df)),
        })

    qualified.sort(key=lambda p: p["adf_p_value"])
    return {
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_date": session_date or date.today().isoformat(),
        "z_window_bars": Z_WINDOW,
        "z_entry": Z_ENTRY,
        "coint_p_max": COINT_P_MAX,
        "corr_window": CORR_WINDOW,
        "corr_threshold": CORR_THRESHOLD,
        "min_hourly_bars": MIN_HOURLY_BARS,
        "pairs": qualified,
    }


def write_pairs_today(payload: dict, path: str = PAIRS_TODAY_FILE):
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


if __name__ == "__main__":
    bars_path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else "pairs_hourly_bars.json"
    session_date = None
    if "--session-date" in sys.argv:
        session_date = sys.argv[sys.argv.index("--session-date") + 1]

    with open(bars_path) as f:
        bars_by_symbol = json.load(f)

    payload = build_pairs_today(bars_by_symbol, session_date=session_date)
    write_pairs_today(payload)

    print(f"=== Pairs DAILY TIER @ {payload['computed_at_utc']} "
          f"(session {payload['session_date']}) ===")
    print(f"cointegration p < {COINT_P_MAX}, |corr| >= {CORR_THRESHOLD}, "
          f">= {MIN_HOURLY_BARS} aligned hourly bars")
    print(f"\n{len(payload['pairs'])} pair(s) qualified for today -> {PAIRS_TODAY_FILE}")
    for p in payload["pairs"]:
        print(f"  {p['pair']:14s}  beta={p['hedge_ratio']:+.4f}  "
              f"p={p['adf_p_value']:.4f}  |corr|={p['abs_corr']:.3f}  "
              f"({p['hourly_bars_used']} bars)")
    if not payload["pairs"]:
        print("  (none -- the intraday tier will trade nothing today)")

    print("\nSIGNAL-ONLY -- no order tool was called. The intraday tier "
          "(pairs_arb_scanner.py) reads pairs_today.json every cycle.")
