"""
SMC Volume Profile signal engine.

Pure calculation functions — no broker library, no credentials, no network
calls. This module takes OHLCV data (already fetched through Claude's
authorized Robinhood connection via get_equity_historicals) and returns a
trade signal. It does NOT place orders; see bot_runbook.md for how signals
turn into orders under human/guardrail control.

Expected input DataFrame columns (matches get_equity_historicals output
after normalization): 'open', 'high', 'low', 'close', 'volume', 'begins_at'.
"""

import numpy as np
import pandas as pd


def calculate_volume_profile_poc(df_candles: pd.DataFrame, bins: int = 20) -> float:
    """
    Point of Control (POC): the price level with the most traded volume.

    Improvement over a naive close-only histogram: each candle's volume is
    distributed across its full high-low range (assumed uniform), not just
    dumped on the close price. This avoids under-weighting price levels a
    candle passed through but didn't close at.
    """
    highs = df_candles["high"].astype(float).values
    lows = df_candles["low"].astype(float).values
    volumes = df_candles["volume"].astype(float).values

    lo, hi = lows.min(), highs.max()
    if hi <= lo:
        return round(float(hi), 2)

    edges = np.linspace(lo, hi, bins + 1)
    bin_volume = np.zeros(bins)

    for h, l, v in zip(highs, lows, volumes):
        if v <= 0:
            continue
        # which bins does this candle's range overlap?
        start_bin = np.searchsorted(edges, l, side="right") - 1
        end_bin = np.searchsorted(edges, h, side="right") - 1
        start_bin = max(0, min(start_bin, bins - 1))
        end_bin = max(0, min(end_bin, bins - 1))
        span = end_bin - start_bin + 1
        # split this candle's volume evenly across the bins it touched
        bin_volume[start_bin:end_bin + 1] += v / span

    max_vol_index = int(np.argmax(bin_volume))
    poc_price = (edges[max_vol_index] + edges[max_vol_index + 1]) / 2.0
    return round(float(poc_price), 2)


def check_consolidation_status(df_candles: pd.DataFrame, threshold_pct: float = 0.015):
    """
    True if the high-low spread over the window is under threshold_pct
    (default 1.5%) of the range low — i.e. the market is chopping, not
    trending. Signals are ignored while this is True.
    """
    highs = df_candles["high"].astype(float)
    lows = df_candles["low"].astype(float)

    range_max = float(highs.max())
    range_min = float(lows.min())
    spread_pct = (range_max - range_min) / range_min
    is_consolidating = spread_pct <= threshold_pct
    return is_consolidating, range_max, range_min


def detect_smc_manipulation_reversal(df: pd.DataFrame, consolidation_bars: int = 12):
    """
    df: OHLCV candles, most recent last, at whatever interval the caller
    fetched (the original design used 15-minute bars).

    Returns (signal, poc_price) where signal is one of:
      "NO_ENTRY"            — still consolidating, standby
      "BULLISH_POC_RETEST"  — swept below support, reclaimed POC -> call
      "BEARISH_POC_RETEST"  — swept above resistance, lost POC -> put
      "NEUTRAL"             — trending but no valid retest trigger yet
    """
    if len(df) < consolidation_bars + 2:
        return "NO_ENTRY", None

    consolidation_window = df.iloc[-(consolidation_bars + 2):-2]
    recent = df.iloc[-2:]  # [previous_candle, current_candle]

    is_consolidating, cons_high, cons_low = check_consolidation_status(consolidation_window)
    if is_consolidating:
        return "NO_ENTRY", None

    poc_price = calculate_volume_profile_poc(consolidation_window)

    prev, curr = recent.iloc[-2], recent.iloc[-1]

    swept_below_support = (prev["low"] < cons_low) or (curr["low"] < cons_low)
    retesting_poc_upward = (curr["close"] >= poc_price) and (prev["close"] < poc_price)
    if swept_below_support and retesting_poc_upward:
        return "BULLISH_POC_RETEST", poc_price

    swept_above_resistance = (prev["high"] > cons_high) or (curr["high"] > cons_high)
    retesting_poc_downward = (curr["close"] <= poc_price) and (prev["close"] > poc_price)
    if swept_above_resistance and retesting_poc_downward:
        return "BEARISH_POC_RETEST", poc_price

    return "NEUTRAL", poc_price


def normalize_rbh_historicals(raw_bars: list) -> pd.DataFrame:
    """
    Adapts get_equity_historicals()'s bar objects to the column names this
    module expects. Adjust field names here if the tool's schema differs
    from what's assumed below (open_price/high_price/etc. vs open/high/etc).
    """
    df = pd.DataFrame(raw_bars)
    rename_map = {
        "open_price": "open", "high_price": "high",
        "low_price": "low", "close_price": "close",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df
