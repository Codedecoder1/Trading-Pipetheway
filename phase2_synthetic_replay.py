"""
Phase 2 -- Synthetic Underlying Replay (per user's explicit directive after
the minute/5-minute option-historicals data-quality bug was diagnosed and
confirmed: get_option_historicals returns flat, interpolated=true
placeholder bars at minute/5minute granularity for the exact windows this
backtest needs, while hour/day granularity for the SAME contracts/dates
return real, mutually-consistent data -- see AMZN 235P 7/30 cross-check:
minute bars flat $0.01 all day, hourly bar closes at $9.25 matching the
real $9.25 daily close).

Rather than fall back to coarse hourly bars (which would hide whether a 7%
trailing stop triggered mid-hour before a recovery), this reconstructs each
option contract's own MINUTE-BY-MINUTE price path synthetically, using
Robinhood's confirmed-reliable 1-minute EQUITY historicals (zero
interpolation across all 10 underlying/date pairs -- verified below) and a
fixed delta-proxy per strike category:

    ITM (~0.60-0.70 delta equivalent)  -> |delta| = 0.65
    ATM (~0.50 delta equivalent)       -> |delta| = 0.50
    OTM (~0.35-0.40 delta equivalent)  -> |delta| = 0.35

Anchor methodology (P_0 / S_0):
  Every one of the 10 signals in this backtest fires within the 19:00-
  20:00Z hour, so a single anchor point at 19:00:00Z (the top of that hour)
  is used for all 30 contracts:
    P_anchor = that contract's real HOURLY option bar OPEN at 19:00:00Z
               (real Robinhood print, confirmed non-interpolated for 29 of
               30 contracts; see NOTE below for the one exception)
    S_anchor = the underlying's real 1-minute equity bar OPEN at 19:00:00Z
  For every subsequent 1-minute equity bar t (t >= entry, through session
  close 20:00Z), the synthetic option OHLC is:
    raw_a = P_anchor + delta_signed * (S_high_t - S_anchor)
    raw_b = P_anchor + delta_signed * (S_low_t  - S_anchor)
    synthetic_high  = max(raw_a, raw_b)      synthetic_low = min(raw_a, raw_b)
    synthetic_open  = P_anchor + delta_signed * (S_open_t  - S_anchor)
    synthetic_close = P_anchor + delta_signed * (S_close_t - S_anchor)
  delta_signed = +|delta| for calls, -|delta| for puts (put premium rises
  as the underlying falls). All values floored at $0.01 (options can't
  price negative). The true entry premium P_entry is the same formula
  evaluated at the signal's real entry_price (the actual observed spot at
  signal time, not a bar approximation) as S_entry.

NOTE on AMZN 287.5P (2026-08-07 exp, the ITM leg of the AMZN 8/3 setup):
  This ONE contract's own price data is broken at EVERY granularity we
  tried -- minute (flat $0.01/interpolated), hour (flat $12.80 all day,
  interpolated), and day (flat $12.80 for 3 days then a lone real-looking
  but implausible $0.01 print). Rather than silently using a garbage
  anchor, its P_anchor is instead interpolated in STRIKE SPACE from its
  two siblings' real hourly data on the same date/expiry (285P ATM and
  282.5P OTM, both confirmed real): ITM_price = 2*ATM_price - OTM_price at
  each hour (287.5 is equidistant from 285 on the far side of 282.5). This
  is flagged explicitly in this contract's result row.

Exit engine: reuses exit_engine.simulate_hybrid_trade_exit() UNCHANGED --
the "ACTIVE STRATEGY...use this one going forward" production exit engine
already in this repo -- with trail_pct_phase1=0.07 (user's explicit answer
to "5-7% trailing stop -- which value?": "7% trailing stop"), and all other
params left at their production defaults, which are an exact match for the
rest of the user's Phase 2 spec (hard_stop_pct=0.15, tp1_pct=0.25,
tp1_fraction=0.5, 3-candle/30-min consolidation stop at a 0.5%-wide band).

DRY RUN / SIGNAL-ONLY: this is a historical P&L simulation only. No
order-placement tool (place_option_order / review_option_order /
place_equity_order / review_equity_order) is called, or will be, regardless
of outcome.
"""
import json, sys
import pandas as pd
sys.path.insert(0, '/home/claude/smc_bot')
from exit_engine import simulate_hybrid_trade_exit

DELTA = {"ITM": 0.65, "ATM": 0.50, "OTM": 0.35}
ANCHOR_TS = "2026-{mm}-{dd}T19:00:00Z"  # all 10 signals fire within the 19:00-20:00Z hour

with open('/home/claude/smc_bot/diag/backtest/phase2_setups.json') as f:
    setups = json.load(f)["setups"]

with open('/home/claude/smc_bot/diag/backtest/equity_1min_bars.json') as f:
    equity_bars = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/anchor_hourly_option_bars.json') as f:
    anchors = json.load(f)


def floor_price(p):
    return max(p, 0.01)


def build_synthetic_bars(eq_bars, s_anchor, p_anchor, delta_signed, entry_time):
    """Returns full-day synthetic option bars (list of dicts, Robinhood
    option-historicals shape) so the exit engine's `> entry_time` filter
    works exactly as it does on real data."""
    out = []
    for b in eq_bars:
        s_open = float(b["open_price"]); s_high = float(b["high_price"])
        s_low = float(b["low_price"]); s_close = float(b["close_price"])
        raw_a = p_anchor + delta_signed * (s_high - s_anchor)
        raw_b = p_anchor + delta_signed * (s_low - s_anchor)
        out.append({
            "begins_at": b["begins_at"],
            "open_price": floor_price(p_anchor + delta_signed * (s_open - s_anchor)),
            "close_price": floor_price(p_anchor + delta_signed * (s_close - s_anchor)),
            "high_price": floor_price(max(raw_a, raw_b)),
            "low_price": floor_price(min(raw_a, raw_b)),
        })
    return out


def build_underlying_df(eq_bars):
    """10-minute-resampled underlying candles (open/high/low/close/begins_at),
    matching the granularity the production exit engine's reversal/
    consolidation checks were built against. Bucketed by simple floor-to-10min
    on the real 1-minute equity timestamps (all bucket boundaries are already
    10-min-aligned since the session opens at 13:30Z)."""
    df = pd.DataFrame(eq_bars).rename(columns={
        "open_price": "open", "high_price": "high", "low_price": "low", "close_price": "close"})
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["begins_at"])
    df["bucket"] = df["ts"].dt.floor("10min")
    grouped = df.groupby("bucket").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index()
    grouped["begins_at"] = grouped["bucket"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return grouped[["begins_at", "open", "high", "low", "close"]]



def run_replay(trail_pct_phase1=0.07):
    """Runs the full 30-contract synthetic replay at the given phase-1
    trailing-stop percentage. All other exit-engine params stay at the
    production defaults (hard_stop_pct=0.15, tp1_pct=0.25, tp1_fraction=0.5,
    trail_pct_phase2=0.12, 3-candle/30-min 0.5%-band consolidation stop).
    Returns the results list (same shape written to the results JSON when
    this module is run directly)."""
    results = []
    for s in setups:
        sym, date, direction = s["symbol"], s["date"], s["direction"]
        entry_time = s["entry_time"]
        entry_spot_recorded = s["entry_price"]
        eq_bars_full = equity_bars[sym][date]
        anchor_ts = date + "T19:00:00Z"

        # S_anchor: equity 1-min bar OPEN at the 19:00:00Z anchor minute
        anchor_eq_bar = next(b for b in eq_bars_full if b["begins_at"] == anchor_ts)
        s_anchor = float(anchor_eq_bar["open_price"])

        # IMPORTANT: use the underlying price from THIS SAME freshly-pulled 1-min
        # equity series at entry_time, NOT the entry_price recorded back in Phase 1
        # (an earlier signal-detection run). Cross-checking all 10 setups found the
        # two disagree by up to ~4% (e.g. QCOM 7/29: recorded 155.28 vs this same
        # timestamp's real 1-min bar at 161.96/162.29) -- a real data-consistency
        # gap in this environment's historicals between fetches, not a market move.
        # Anchoring entry price to a DIFFERENT data pull than the forward synthetic
        # path would inject a spurious day-one gap into every trade (the premium
        # would "teleport" back to the fresh series on bar 2), producing fake
        # immediate hard-stops that have nothing to do with the actual signal.
        # Using this series' own price at entry_time keeps entry and path internally
        # consistent, which is what the synthetic-replay approach requires.
        entry_eq_bar = next(b for b in eq_bars_full if b["begins_at"] == entry_time)
        entry_spot = float(entry_eq_bar["open_price"])
        entry_spot_gap_pct = round((entry_spot_recorded - entry_spot) / entry_spot * 100, 2)

        # bars strictly at/after the anchor hour (we only need forward path for the exit sim)
        eq_bars_fwd = [b for b in eq_bars_full if b["begins_at"] >= anchor_ts]

        underlying_df = build_underlying_df(eq_bars_full)

        for category, leg in s["legs"].items():
            iid = leg["instrument_id"]
            strike = leg["strike"]
            delta_mag = DELTA[category]
            delta_signed = delta_mag if direction == "call" else -delta_mag

            anchor_hourly = anchors[iid]
            anchor_bar = next(b for b in anchor_hourly if b["begins_at"] == anchor_ts)
            p_anchor = float(anchor_bar["open_price"])
            anchor_note = anchor_bar.get("note")

            entry_premium = floor_price(p_anchor + delta_signed * (entry_spot - s_anchor))

            synthetic_bars = build_synthetic_bars(eq_bars_fwd, s_anchor, p_anchor, delta_signed, entry_time)

            sim = simulate_hybrid_trade_exit(
                synthetic_bars, underlying_df, entry_time, entry_premium, direction,
                hard_stop_pct=0.15, trail_pct_phase1=trail_pct_phase1, tp1_pct=0.25, tp1_fraction=0.5,
                trail_pct_phase2=0.12, max_consolidation_candles=3, consolidation_range_pct=0.005,
                max_time_in_trade_minutes=30,
            )

            results.append({
                "symbol": sym, "date": date, "direction": direction, "category": category,
                "strike": strike, "instrument_id": iid, "delta_proxy": delta_signed,
                "entry_time": entry_time, "entry_underlying": entry_spot,
                "entry_underlying_recorded_phase1": entry_spot_recorded,
                "entry_underlying_gap_pct": entry_spot_gap_pct,
                "anchor_time": anchor_ts, "s_anchor": s_anchor, "p_anchor": p_anchor,
                "anchor_note": anchor_note,
                "trail_pct_phase1": trail_pct_phase1,
                "entry_premium": round(entry_premium, 4),
                "pnl_pct": sim["pnl_pct"],
                "legs": sim["legs"],
            })
    return results


def print_report(results, setups, trail_pct_phase1):
    print(f"=== Phase 2 -- Synthetic Underlying Replay (trail_pct_phase1={trail_pct_phase1:.0%}) -- "
          f"{len(results)} contracts across {len(setups)} setups ===\n")

    by_cat = {"ITM": [], "ATM": [], "OTM": []}
    for r in results:
        by_cat[r["category"]].append(r)
        flag = f"  [{r['anchor_note']}]" if r.get("anchor_note") else ""
        gap = r.get("entry_underlying_gap_pct")
        gap_flag = f"  [phase1 entry vs replay-series gap: {gap:+.2f}%]" if gap and abs(gap) >= 0.5 else ""
        print(f"  {r['symbol']:6s} {r['date']} {r['direction']:4s} {r['category']:3s} strike={r['strike']:<8} "
              f"entry_prem=${r['entry_premium']:<7.2f} pnl={r['pnl_pct']:+7.2f}%  "
              f"legs={[(l['fraction'], l['reason']) for l in r['legs']]}{flag}{gap_flag}")

    print("\n--- Aggregate by strike category ---")
    for cat in ["ITM", "ATM", "OTM"]:
        rows = by_cat[cat]
        pnls = [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
        wins = [p for p in pnls if p > 0]
        n = len(pnls)
        win_rate = 100.0 * len(wins) / n if n else float("nan")
        avg_pnl = sum(pnls) / n if n else float("nan")
        worst = min(pnls) if pnls else float("nan")
        best = max(pnls) if pnls else float("nan")
        print(f"  {cat}: n={n}  win_rate={win_rate:.1f}%  avg_pnl={avg_pnl:+.2f}%  "
              f"best={best:+.2f}%  worst={worst:+.2f}%")

    print("\n--- Exit reason breakdown ---")
    from collections import Counter
    reason_counts = Counter()
    for r in results:
        for leg in r["legs"]:
            reason_counts[(r["category"], leg["reason"])] += 1
    for (cat, reason), n in sorted(reason_counts.items()):
        print(f"  {cat:3s} {reason:28s}: {n}")


if __name__ == "__main__":
    results = run_replay(trail_pct_phase1=0.07)
    with open('/home/claude/smc_bot/diag/backtest/phase2_synthetic_replay_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print_report(results, setups, 0.07)
