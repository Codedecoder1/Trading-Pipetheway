"""
debit_spread_filters.py -- Gate 0 & Gate 1 filters for daily Debit Spread strategy.

WHAT IT DOES
Gate the stock universe for Debit Spread eligibility:
1. Trend Direction (Gate 0) — price vs 200-VWAP + ADX > 20
2. Earnings Blackout (Gate 0) — reject if earnings within ±10 days
3. Intraday Volatility (Gate 0) — require RVOL >= 1.5

Input: symbol, recent bars (OHLCV), today's date, earnings calendar
Output: True/False for "this symbol is eligible right now"

USAGE (from orchestrator, e.g., debit_spread_scanner.py):
  from debit_spread_filters import (
      check_trend_gate, check_earnings_gate, check_rvol_gate
  )

  is_call_candidate = check_trend_gate(bars, direction="call")
  not_in_blackout = check_earnings_gate(symbol, earnings_calendar, today)
  has_volume = check_rvol_gate(bars, min_rvol=1.5)

  if is_call_candidate and not_in_blackout and has_volume:
      # Proceed to strike selection
"""

import sys
from datetime import datetime, timedelta

VWAP_PERIOD = 200
ADX_THRESHOLD = 20.0
MIN_RVOL = 1.5
EARNINGS_BLACKOUT_DAYS = 10


def compute_vwap(bars, period=VWAP_PERIOD):
    """Compute rolling VWAP over last `period` bars (or all available)."""
    if not bars or len(bars) < 2:
        return None
    window = bars[-period:] if len(bars) >= period else bars
    tp_vol = sum((b["high_price"] + b["low_price"] + b["close_price"]) / 3 * b["volume"]
                 for b in window)
    total_vol = sum(b["volume"] for b in window)
    return tp_vol / total_vol if total_vol > 0 else None


def compute_adx(bars, period=14):
    """
    Simple ADX(14) approximation: average of true ranges, smoothed.
    For a full implementation use pandas_ta or manual EMA; this is a placeholder.
    Returns None if insufficient data.
    """
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h = bars[i]["high_price"]
        l = bars[i]["low_price"]
        c_prev = bars[i - 1]["close_price"]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    atr = sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / len(trs)
    return atr if atr > 0 else None


def check_trend_gate(bars, direction="call"):
    """
    Gate 0 Trend Direction:
    - For Call Spreads: require close > 200-VWAP AND ADX(14) > 20 (uptrend)
    - For Put Spreads: require close < 200-VWAP AND ADX(14) > 20 (downtrend)

    Returns True if trend matches direction and ADX confirms.
    """
    if not bars or len(bars) < 200:
        return False

    latest = bars[-1]
    close = latest["close_price"]
    vwap = compute_vwap(bars, VWAP_PERIOD)
    adx = compute_adx(bars)

    if vwap is None or adx is None:
        return False

    if adx <= ADX_THRESHOLD:
        return False

    if direction == "call":
        return close > vwap
    elif direction == "put":
        return close < vwap
    else:
        return False


def check_earnings_gate(symbol, earnings_calendar, scan_date):
    """
    Gate 0 Earnings Blackout:
    Reject if an earnings report is scheduled within ±10 days of scan_date.

    earnings_calendar: list of dicts, each with 'symbol' and 'report_date' (ISO string)
    scan_date: ISO string (e.g., "2026-09-15")

    Returns True if symbol is NOT in blackout (i.e., OK to trade).
    Returns False if earnings within ±10 days.
    """
    if not earnings_calendar:
        # No calendar data = assume OK (could also be conservative and reject)
        return True

    try:
        scan_dt = datetime.fromisoformat(scan_date.replace("Z", "+00:00")).date()
    except ValueError:
        return False

    for event in earnings_calendar:
        if event.get("symbol", "").upper() != symbol.upper():
            continue
        try:
            report_dt = datetime.fromisoformat(
                event.get("report_date", "").replace("Z", "+00:00")
            ).date()
            days_away = abs((report_dt - scan_dt).days)
            if days_away <= EARNINGS_BLACKOUT_DAYS:
                return False  # In blackout window
        except (ValueError, TypeError):
            continue

    return True  # Not in blackout


def check_rvol_gate(bars, min_rvol=MIN_RVOL):
    """
    Gate 0 Intraday Volatility:
    Require Relative Volume (today's volume / avg 20-day volume) >= min_rvol.

    Returns True if RVOL >= threshold.
    """
    if len(bars) < 21:
        return False

    today_vol = bars[-1]["volume"]
    if today_vol == 0:
        return False

    avg_vol_20 = sum(b["volume"] for b in bars[-21:-1]) / 20
    if avg_vol_20 == 0:
        return False

    rvol = today_vol / avg_vol_20
    return rvol >= min_rvol
