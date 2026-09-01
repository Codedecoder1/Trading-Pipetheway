"""
Combined entry rule: SMC POC-retest structure AND a matching-direction
candlestick pattern must BOTH be present on the same candle. Per your
instruction, this replaces "POC retest alone" as the entry trigger --
the bot only enters when it has found a specific, named confirming
pattern alongside the structural retest. No candlestick match = no entry,
even if the POC-retest condition alone would have fired.
"""

from smc_engine import check_consolidation_status as check_consolidation, calculate_volume_profile_poc
from candlestick_patterns import confirm_pattern


def detect_confluence_signal(df, consolidation_bars=18, threshold_pct=0.015):
    """
    Returns (signal, poc_price, candlestick_pattern) where signal is one of
    "NO_ENTRY" (still consolidating), "NO_CONFIRMATION" (POC-retest
    structure present but no matching candlestick pattern -- do not enter),
    "BULLISH_CONFLUENCE", or "BEARISH_CONFLUENCE".

    consolidation_bars: how many candles form the base/range window used to
    compute the POC and the sweep boundaries. Shorter = the base refreshes
    faster, so more independent setups get evaluated across a day.

    threshold_pct: how tight (as a % of the low) that base window's own
    high-low spread must be for the window to still count as "just
    chopping, not tradable yet" -> skipped. LOWER threshold_pct = fewer
    windows get dismissed as "still just chop", so more of them proceed to
    the actual sweep+POC-retest check. This is the "loosen" knob.
    """
    if len(df) < consolidation_bars + 2:
        return "NO_ENTRY", None, None

    window = df.iloc[-(consolidation_bars + 2):-2]
    recent = df.iloc[-2:]
    is_consol, cons_hi, cons_lo = check_consolidation(window, threshold_pct=threshold_pct)
    if is_consol:
        return "NO_ENTRY", None, None

    poc = calculate_volume_profile_poc(window)
    prev, curr = recent.iloc[-2], recent.iloc[-1]

    swept_below = (prev["low"] < cons_lo) or (curr["low"] < cons_lo)
    retest_up = (curr["close"] >= poc) and (prev["close"] < poc)
    if swept_below and retest_up:
        pattern = confirm_pattern(df, "bullish")
        if pattern:
            return "BULLISH_CONFLUENCE", poc, pattern
        return "NO_CONFIRMATION", poc, None

    swept_above = (prev["high"] > cons_hi) or (curr["high"] > cons_hi)
    retest_down = (curr["close"] <= poc) and (prev["close"] > poc)
    if swept_above and retest_down:
        pattern = confirm_pattern(df, "bearish")
        if pattern:
            return "BEARISH_CONFLUENCE", poc, pattern
        return "NO_CONFIRMATION", poc, None

    return "NO_ENTRY", poc, None
