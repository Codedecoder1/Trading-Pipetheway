"""
Exit simulation for long option positions (calls or puts).

*** ACTIVE STRATEGY: simulate_hybrid_trade_exit() ***
This is the one to use for all exit simulation going forward (adopted
2026-08-25, after a real-data comparison across 9 Monday trades plus a
$150-starting-capital dollar simulation -- see /home/claude/smc_bot/diag/
exit_strategy_comparison.md, time_decay_refined_findings.md,
hybrid_exit_findings.md, and dollar_comparison_150.md for the full
analysis and reasoning). It replaces the legacy strategy below because it
puts an actual floor under losing trades (a demonstrated -15% -> -3%
improvement on the one losing trade in that comparison) instead of riding
a loser all the way down before any protection kicks in, while still
letting winners run further than a flat 3% trail would.

Legacy strategy (trailing_stop_exit / poc_reversal_exit / simulate_trade_exit,
kept below for reference and as the "OLD" baseline in comparisons): 100% of
the position exits on a 3% trailing stop on premium, OR a POC-reversal
signal on the underlying, whichever triggers first. No hard floor, no
partial profit-taking, no time limit.

Hybrid strategy structure (simulate_hybrid_trade_exit):
  Phase 1 (entry -> TP1):
    - Hard stop -15% on premium, active from entry, highest priority.
    - Active trailing stop 6%, off the highest premium seen since entry.
    - Take-profit-1 target +25% -> closes 50% of the ORIGINAL position size,
      moves the remainder into phase 2.
  Phase 2 (runner, only after TP1 fires):
    - Active trailing stop 12%, off the highest premium seen since TP1.
    - AI reversal exit: candlestick-pattern + wick-ratio + 20-EMA signal on
      the UNDERLYING (bearish engulfing / upper-wick>50%-of-range /
      close-below-20EMA for calls, mirrored for puts) -- exits whatever
      remains, 100%. Only monitored in phase 2 per the spec this was built
      from.
  Consolidation/time stop (global, both phases):
    - Force-close whatever remains at the EARLIER of: 3 consecutive 10-min
      underlying candles whose combined high/low range is within +/-0.25%
      (a 0.5%-wide band, same shape as check_consolidation_status below), or
      an absolute 30-minute-in-trade backstop that fires regardless of
      whether the consolidation condition ever confirms.

Because we're always LONG an option (call or put -- direction only decides
which one we bought), "profit" always means the option's own premium going
UP. So every trailing-stop leg below is identical in shape for calls and
puts: track the highest premium seen since some reference point, exit if
premium pulls back trail_pct off that peak. Direction only matters for the
legs that watch the UNDERLYING for a structural signal (POC-reversal for
the legacy strategy, the candlestick/EMA reversal trigger for the hybrid
one).

Bar-order convention for every trailing stop in this file: within each bar
we check the LOW against the trailing-stop level BEFORE updating the peak
with that bar's HIGH. That's the conservative (worst-case-for-us) ordering
-- it assumes the low could have printed first.
"""

import pandas as pd
from smc_engine import calculate_volume_profile_poc, check_consolidation_status
from candlestick_patterns import _metrics, _bearish_engulfing, _bullish_engulfing


def trailing_stop_exit(option_bars, entry_price, entry_time, trail_pct=0.03):
    """
    option_bars: list of dicts with begins_at/open_price/high_price/low_price/close_price
    (Robinhood's raw option-historicals bar shape), already covering the
    period from entry onward. Returns (exit_time, exit_price, peak_price) or
    (None, None, peak) if the stop never triggers within the given bars.
    """
    peak = entry_price
    for bar in option_bars:
        if bar["begins_at"] <= entry_time:
            continue
        low = float(bar["low_price"])
        high = float(bar["high_price"])
        stop_level = peak * (1 - trail_pct)
        if low <= stop_level:
            return bar["begins_at"], round(stop_level, 4), peak
        peak = max(peak, high)
    return None, None, peak


def poc_reversal_exit(underlying_df, entry_time, entry_direction, consolidation_bars=18):
    """
    underlying_df: DataFrame of underlying candles (open/high/low/close/
    begins_at columns), covering the full day so we have enough history to
    build the rolling consolidation window at every point after entry.
    entry_direction: "BEARISH_POC_RETEST" or "BULLISH_POC_RETEST" -- the
    signal we entered on. We're watching for the OPPOSITE signal to fire
    afterward, which means smart money reversed again and our thesis is
    invalidated.
    Returns (exit_time, exit_price) or (None, None) if no reversal found.
    """
    opposite = "BULLISH_POC_RETEST" if entry_direction == "BEARISH_POC_RETEST" else "BEARISH_POC_RETEST"
    for end in range(consolidation_bars + 2, len(underlying_df) + 1):
        sub = underlying_df.iloc[:end]
        ts = sub.iloc[-1]["begins_at"]
        if ts <= entry_time:
            continue
        window = sub.iloc[-(consolidation_bars + 2):-2]
        recent = sub.iloc[-2:]
        is_consol, cons_hi, cons_lo = check_consolidation_status(window)
        if is_consol:
            continue
        poc = calculate_volume_profile_poc(window)
        prev, curr = recent.iloc[-2], recent.iloc[-1]
        swept_below = (prev["low"] < cons_lo) or (curr["low"] < cons_lo)
        retest_up = (curr["close"] >= poc) and (prev["close"] < poc)
        swept_above = (prev["high"] > cons_hi) or (curr["high"] > cons_hi)
        retest_down = (curr["close"] <= poc) and (prev["close"] > poc)
        if opposite == "BULLISH_POC_RETEST" and swept_below and retest_up:
            return ts, float(curr["close"])
        if opposite == "BEARISH_POC_RETEST" and swept_above and retest_down:
            return ts, float(curr["close"])
    return None, None


def simulate_trade_exit(option_bars, underlying_df, entry_time, entry_price,
                         entry_direction, trail_pct=0.03, consolidation_bars=18):
    """
    Runs both exit legs and returns whichever fires first (by timestamp).
    Returns a dict: entry_time, entry_price, exit_time, exit_reason,
    exit_price (option premium if trailing-stop, else None -- POC-reversal
    exits on structure, not a specific premium print, so we report the
    underlying's exit price separately), pnl_pct, peak_premium.
    """
    ts_stop, price_stop, peak = trailing_stop_exit(option_bars, entry_price, entry_time, trail_pct)
    ts_poc, underlying_exit_price = poc_reversal_exit(underlying_df, entry_time, entry_direction, consolidation_bars)

    candidates = []
    if ts_stop:
        candidates.append(("TRAILING_STOP", ts_stop, price_stop))
    if ts_poc:
        candidates.append(("POC_REVERSAL", ts_poc, None))

    if not candidates:
        return {
            "entry_time": entry_time, "entry_price": entry_price,
            "exit_time": None, "exit_reason": "STILL_OPEN",
            "exit_price": None, "pnl_pct": None, "peak_premium": peak,
        }

    candidates.sort(key=lambda x: x[1])
    reason, exit_time, exit_price = candidates[0]

    if reason == "POC_REVERSAL" and exit_price is None:
        # find the option premium at/after that timestamp to mark the exit
        for bar in option_bars:
            if bar["begins_at"] >= exit_time:
                exit_price = float(bar["open_price"])
                break
        if exit_price is None:
            exit_price = entry_price  # fallback, shouldn't normally happen

    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
    return {
        "entry_time": entry_time, "entry_price": entry_price,
        "exit_time": exit_time, "exit_reason": reason,
        "exit_price": round(exit_price, 4), "pnl_pct": pnl_pct,
        "peak_premium": round(peak, 4),
    }


# =====================================================================
# HYBRID STRATEGY -- active as of 2026-08-25, use this one going forward.
# =====================================================================

def _ema(series, period=20):
    return series.ewm(span=period, adjust=False).mean()


def reversal_signal_exit(underlying_df, entry_time, direction):
    """
    direction: 'call' or 'put' (what we bought). Checks each 10-min bar
    after entry_time for the AI reversal trigger: candlestick-pattern +
    wick-ratio>50% + close vs 20-EMA, direction-aware. Returns (exit_time,
    exit_close_price) at the FIRST bar where all 3 conditions align, or
    (None, None).
    """
    df = underlying_df.copy()
    df["ema20"] = _ema(df["close"], 20)
    for i in range(1, len(df)):
        ts = underlying_df.iloc[i]["begins_at"] if "begins_at" in underlying_df.columns else None
        if ts is None or ts <= entry_time:
            continue
        prev_m = _metrics(df.iloc[i - 1])
        curr_m = _metrics(df.iloc[i])
        close = df.iloc[i]["close"]
        ema20 = df.iloc[i]["ema20"]
        if direction == "call":
            engulf = _bearish_engulfing(prev_m, curr_m)
            wick = curr_m["upper_wick"] / curr_m["rng"] > 0.50 if curr_m["rng"] > 0 else False
            below_ema = close < ema20
            if engulf and wick and below_ema:
                return ts, float(close)
        else:
            engulf = _bullish_engulfing(prev_m, curr_m)
            wick = curr_m["lower_wick"] / curr_m["rng"] > 0.50 if curr_m["rng"] > 0 else False
            above_ema = close > ema20
            if engulf and wick and above_ema:
                return ts, float(close)
    return None, None


def time_decay_exit(underlying_df, entry_time, max_consolidation_candles=3,
                     range_pct=0.005, max_time_in_trade_minutes=30):
    """
    Force-close whatever remains at the EARLIER of:
      (a) 3 CONSECUTIVE 10-min underlying candles whose combined high/low
          range is within +/-0.25% (0.5%-wide band -> range_pct=0.005,
          same math as check_consolidation_status above, just applied to a
          fixed-size rolling window instead of the strategy's usual
          consolidation_bars window).
      (b) an absolute max_time_in_trade_minutes backstop that fires
          regardless of whether (a) ever confirms.
    Returns (exit_ts, reason) for whichever of (a)/(b) comes first.
    reason is "TIME_DECAY_CONSOLIDATION" or "TIME_DECAY_BACKSTOP".
    """
    und_after = underlying_df[underlying_df["begins_at"] > entry_time].reset_index(drop=True)

    consolidation_ts = None
    for i in range(len(und_after) - max_consolidation_candles + 1):
        window = und_after.iloc[i:i + max_consolidation_candles]
        is_consolidating, _, _ = check_consolidation_status(window, threshold_pct=range_pct)
        if is_consolidating:
            consolidation_ts = window.iloc[-1]["begins_at"]
            break

    entry_ts = pd.Timestamp(entry_time)
    backstop_ts = (entry_ts + pd.Timedelta(minutes=max_time_in_trade_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    candidates = []
    if consolidation_ts is not None:
        candidates.append((consolidation_ts, "TIME_DECAY_CONSOLIDATION"))
    candidates.append((backstop_ts, "TIME_DECAY_BACKSTOP"))
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def simulate_hybrid_trade_exit(option_bars, underlying_df, entry_time, entry_price, direction,
                                hard_stop_pct=0.15, trail_pct_phase1=0.06,
                                tp1_pct=0.25, tp1_fraction=0.5, trail_pct_phase2=0.12,
                                max_consolidation_candles=3, consolidation_range_pct=0.005,
                                max_time_in_trade_minutes=30):
    """
    direction: 'call' or 'put'. option_bars: list of dicts (Robinhood's raw
    option-historicals bar shape) covering the period from entry onward.
    underlying_df: DataFrame of underlying candles (open/high/low/close/
    begins_at), covering the full day.

    Priority per option bar (REVISION 1, 2026-08-27, per explicit user
    request -- see phase2_synthetic_replay/dollar-simulation findings from
    2026-08-26 that surfaced this: a signal entered on the session's last
    5-minute bar holds overnight, the 30-minute time-decay backstop then
    fires on the very next available bar, and under the OLD ordering below
    that meant a loss that had already blown through the -15% hard stop
    (TGT: -27.34%) got marked as a time-decay exit instead of a hard stop
    -- i.e. the hard risk limit was bypassed by a time-based exit on the
    same bar. Hard stop now evaluates first, every bar, in both phases
    where it's active (Phase 1 only -- Phase 2 has no hard-stop leg, so its
    ordering is unchanged):
      1. [Phase 1 only] Hard stop -15% -- whole remaining position. Checked
         BEFORE the time-decay/consolidation backstop so a hard risk limit
         can never be pre-empted by a time-based exit landing on the same
         bar (e.g. an overnight gap after a late-session entry).
      2. Consolidation/time-decay stop (global, both phases) -- whole
         remaining position.
      3. [Phase 1 only] 6% trailing stop off peak-since-entry -- whole
         remaining position.
      4. [Phase 1 only] Take-profit-1 +25% -- closes tp1_fraction of the
         ORIGINAL position size, moves the remainder to phase 2.
      5. [Phase 2 only] 12% trailing stop off peak-since-TP1 -- whole
         remaining position.
      6. [Phase 2 only] AI reversal trigger -- whole remaining position.

    Old priority (superseded by REVISION 1 above, kept here for context):
      1. Consolidation/time-decay stop (global, both phases).
      2. [Phase 1 only] Hard stop -15%.
      ...(3-6 unchanged)

    Returns a dict: entry_price, legs (list of {fraction, exit_time,
    exit_price, reason}), pnl_pct (blended, weighted by fraction of
    original position across all legs).
    """
    bars_after = [b for b in option_bars if b["begins_at"] > entry_time]
    if not bars_after:
        return {"entry_price": entry_price, "legs": [], "pnl_pct": None, "note": "no data after entry"}

    hard_stop_level = entry_price * (1 - hard_stop_pct)
    tp1_level = entry_price * (1 + tp1_pct)
    tp1_done = False
    peak_since_entry = entry_price
    peak_since_tp1 = None
    remaining_frac = 1.0
    legs = []  # (fraction_of_original, exit_time, exit_price, reason)

    rev_time, _ = reversal_signal_exit(underlying_df, entry_time, direction)
    time_decay_ts, time_decay_reason = time_decay_exit(
        underlying_df, entry_time, max_consolidation_candles,
        consolidation_range_pct, max_time_in_trade_minutes)

    for bar in bars_after:
        ts = bar["begins_at"]
        low = float(bar["low_price"])
        high = float(bar["high_price"])

        if not tp1_done:
            # phase 1: entry -> TP1
            # REVISION 1 (2026-08-27): hard stop now checked FIRST, ahead of
            # the time-decay/consolidation backstop below -- a hard risk
            # limit must not be pre-empted by a time-based exit landing on
            # the same bar (e.g. an overnight-gap bar after a late-session
            # entry that blew through -15% before the backstop even fires).
            if low <= hard_stop_level:
                legs.append((remaining_frac, ts, hard_stop_level, "HARD_STOP"))
                remaining_frac = 0
                break

            # global: consolidation/30-min time stop applies in either phase
            if remaining_frac > 0 and time_decay_ts is not None and ts >= time_decay_ts:
                legs.append((remaining_frac, ts, float(bar["open_price"]), time_decay_reason))
                remaining_frac = 0
                break

            peak_since_entry = max(peak_since_entry, high)
            trail_level_p1 = peak_since_entry * (1 - trail_pct_phase1)
            if low <= trail_level_p1:
                legs.append((remaining_frac, ts, trail_level_p1,
                             f"TRAILING_STOP_{int(trail_pct_phase1 * 100)}_PHASE1"))
                remaining_frac = 0
                break

            if high >= tp1_level:
                legs.append((tp1_fraction, ts, tp1_level, "TAKE_PROFIT_1"))
                tp1_done = True
                remaining_frac = round(1.0 - tp1_fraction, 6)
                peak_since_tp1 = tp1_level
        else:
            # phase 2: runner, post-TP1 -- no hard-stop leg here, so
            # time-decay/consolidation stays the first check, unchanged.
            if remaining_frac > 0 and time_decay_ts is not None and ts >= time_decay_ts:
                legs.append((remaining_frac, ts, float(bar["open_price"]), time_decay_reason))
                remaining_frac = 0
                break

            peak_since_tp1 = max(peak_since_tp1, high)
            trail_level_p2 = peak_since_tp1 * (1 - trail_pct_phase2)
            if low <= trail_level_p2:
                legs.append((remaining_frac, ts, trail_level_p2,
                             f"TRAILING_STOP_{int(trail_pct_phase2 * 100)}_PHASE2"))
                remaining_frac = 0
                break

            if rev_time is not None and ts >= rev_time:
                legs.append((remaining_frac, rev_time, float(bar["open_price"]), "AI_REVERSAL"))
                remaining_frac = 0
                break

    if remaining_frac > 0:
        last = bars_after[-1]
        legs.append((remaining_frac, last["begins_at"], float(last["close_price"]), "STILL_OPEN"))

    total_pnl = 0.0
    for frac, ts, price, reason in legs:
        leg_pnl_pct = (price - entry_price) / entry_price * 100
        total_pnl += frac * leg_pnl_pct

    return {
        "entry_price": entry_price,
        "legs": [{"fraction": f, "exit_time": t, "exit_price": round(p, 4), "reason": r} for f, t, p, r in legs],
        "pnl_pct": round(total_pnl, 2),
    }
