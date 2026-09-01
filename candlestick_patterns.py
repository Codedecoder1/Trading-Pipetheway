"""
Classic candlestick reversal patterns, used as a CONFIRMATION FILTER on top
of the SMC POC-retest signal -- per your instruction, the bot only enters
when BOTH agree: the POC-retest structure AND a matching-direction
candlestick pattern at the same candle. Confluence, not two separate
trigger sources.

Covers the 15 bearish patterns from your screenshot, plus the 15 bullish
mirror-image equivalents (for call signals). Definitions below are the
standard heuristic rules used in most TA references -- real-world charts
are messier than textbook diagrams, so these use tolerance bands rather
than exact ratios. Treat this as "reasonably faithful," not "textbook-exact
to the pixel."

All functions take a DataFrame of candles (columns: open, high, low,
close; most recent row LAST) and look at the last 1-5 rows as needed.
Each returns the matched pattern name, or None.
"""

import pandas as pd


def _metrics(row):
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return {
        "o": o, "h": h, "l": l, "c": c, "body": body, "rng": rng,
        "upper_wick": upper_wick, "lower_wick": lower_wick,
        "is_bull": c > o, "is_bear": c < o,
        "body_pct": body / rng,
    }


# ---------------------------------------------------------------- BEARISH --

def _shooting_star(m):
    return m["upper_wick"] >= 2 * m["body"] and m["lower_wick"] <= 0.3 * m["body"] and m["body_pct"] <= 0.35

def _hanging_man(m):
    return m["lower_wick"] >= 2 * m["body"] and m["upper_wick"] <= 0.3 * m["body"] and m["body_pct"] <= 0.35

def _gravestone_doji(m):
    return m["body_pct"] <= 0.08 and m["upper_wick"] >= 0.6 * m["rng"] and m["lower_wick"] <= 0.15 * m["rng"]

def _bearish_marubozu(m):
    return m["is_bear"] and m["body_pct"] >= 0.9

def _bearish_spinning_top(m):
    return m["body_pct"] <= 0.3 and m["upper_wick"] >= m["body"] and m["lower_wick"] >= m["body"]

def _bearish_long_legged_doji(m):
    return m["body_pct"] <= 0.08 and m["upper_wick"] >= 0.35 * m["rng"] and m["lower_wick"] >= 0.35 * m["rng"]

def _bearish_engulfing(p, c):
    return p["is_bull"] and c["is_bear"] and c["o"] >= p["c"] and c["c"] <= p["o"]

def _bearish_harami(p, c):
    return p["is_bull"] and p["body"] > 0 and c["o"] <= p["c"] and c["c"] >= p["o"] and c["body"] < p["body"]

def _dark_cloud_cover(p, c):
    mid = p["o"] + (p["c"] - p["o"]) / 2
    return p["is_bull"] and c["is_bear"] and c["o"] > p["c"] and c["c"] < mid and c["c"] > p["o"]

def _tweezer_top(p, c):
    return abs(p["h"] - c["h"]) <= 0.1 * max(p["rng"], c["rng"]) and p["is_bull"] and c["is_bear"]

def _three_black_crows(a, b, c):
    seq = [a, b, c]
    return all(x["is_bear"] and x["body_pct"] >= 0.5 for x in seq) and \
        b["o"] < a["o"] and b["c"] < a["c"] and c["o"] < b["o"] and c["c"] < b["c"]

def _three_inside_down(a, b, c):
    return _bearish_harami(a, b) and c["is_bear"] and c["c"] < a["o"]

def _three_outside_down(a, b, c):
    return _bearish_engulfing(a, b) and c["is_bear"] and c["c"] < b["c"]

def _evening_star(a, b, c):
    return a["is_bull"] and a["body_pct"] >= 0.5 and b["body_pct"] <= 0.3 and \
        c["is_bear"] and c["c"] < (a["o"] + a["c"]) / 2

def _falling_three_method(bars5):
    a, x1, x2, x3, e = bars5
    return a["is_bear"] and a["body_pct"] >= 0.5 and \
        all(a["l"] <= m["o"] <= a["h"] and a["l"] <= m["c"] <= a["h"] for m in (x1, x2, x3)) and \
        e["is_bear"] and e["c"] < a["c"]

BEARISH_1CANDLE = {
    "Shooting Star": _shooting_star, "Hanging Man": _hanging_man,
    "Gravestone Doji": _gravestone_doji, "Bearish Marubozu": _bearish_marubozu,
    "Bearish Spinning Top": _bearish_spinning_top, "Bearish Long Legged Doji": _bearish_long_legged_doji,
}
BEARISH_2CANDLE = {
    "Bearish Engulfing": _bearish_engulfing, "Bearish Harami": _bearish_harami,
    "Dark Cloud Cover": _dark_cloud_cover, "Tweezer Top": _tweezer_top,
}
BEARISH_3CANDLE = {
    "Three Black Crows": _three_black_crows, "Three Inside Down": _three_inside_down,
    "Three Outside Down": _three_outside_down, "Evening Star": _evening_star,
}


# ---------------------------------------------------------------- BULLISH --
# mirror image of every bearish rule above

def _hammer(m):
    return m["lower_wick"] >= 2 * m["body"] and m["upper_wick"] <= 0.3 * m["body"] and m["body_pct"] <= 0.35

def _inverted_hammer(m):
    return m["upper_wick"] >= 2 * m["body"] and m["lower_wick"] <= 0.3 * m["body"] and m["body_pct"] <= 0.35

def _dragonfly_doji(m):
    return m["body_pct"] <= 0.08 and m["lower_wick"] >= 0.6 * m["rng"] and m["upper_wick"] <= 0.15 * m["rng"]

def _bullish_marubozu(m):
    return m["is_bull"] and m["body_pct"] >= 0.9

def _bullish_spinning_top(m):
    return m["body_pct"] <= 0.3 and m["upper_wick"] >= m["body"] and m["lower_wick"] >= m["body"]

def _bullish_long_legged_doji(m):
    return m["body_pct"] <= 0.08 and m["upper_wick"] >= 0.35 * m["rng"] and m["lower_wick"] >= 0.35 * m["rng"]

def _bullish_engulfing(p, c):
    return p["is_bear"] and c["is_bull"] and c["o"] <= p["c"] and c["c"] >= p["o"]

def _bullish_harami(p, c):
    return p["is_bear"] and p["body"] > 0 and c["o"] >= p["c"] and c["c"] <= p["o"] and c["body"] < p["body"]

def _piercing_line(p, c):
    mid = p["o"] + (p["c"] - p["o"]) / 2
    return p["is_bear"] and c["is_bull"] and c["o"] < p["c"] and c["c"] > mid and c["c"] < p["o"]

def _tweezer_bottom(p, c):
    return abs(p["l"] - c["l"]) <= 0.1 * max(p["rng"], c["rng"]) and p["is_bear"] and c["is_bull"]

def _three_white_soldiers(a, b, c):
    seq = [a, b, c]
    return all(x["is_bull"] and x["body_pct"] >= 0.5 for x in seq) and \
        b["o"] > a["o"] and b["c"] > a["c"] and c["o"] > b["o"] and c["c"] > b["c"]

def _three_inside_up(a, b, c):
    return _bullish_harami(a, b) and c["is_bull"] and c["c"] > a["o"]

def _three_outside_up(a, b, c):
    return _bullish_engulfing(a, b) and c["is_bull"] and c["c"] > b["c"]

def _morning_star(a, b, c):
    return a["is_bear"] and a["body_pct"] >= 0.5 and b["body_pct"] <= 0.3 and \
        c["is_bull"] and c["c"] > (a["o"] + a["c"]) / 2

def _rising_three_method(bars5):
    a, x1, x2, x3, e = bars5
    return a["is_bull"] and a["body_pct"] >= 0.5 and \
        all(a["l"] <= m["o"] <= a["h"] and a["l"] <= m["c"] <= a["h"] for m in (x1, x2, x3)) and \
        e["is_bull"] and e["c"] > a["c"]

BULLISH_1CANDLE = {
    "Hammer": _hammer, "Inverted Hammer": _inverted_hammer,
    "Dragonfly Doji": _dragonfly_doji, "Bullish Marubozu": _bullish_marubozu,
    "Bullish Spinning Top": _bullish_spinning_top, "Bullish Long Legged Doji": _bullish_long_legged_doji,
}
BULLISH_2CANDLE = {
    "Bullish Engulfing": _bullish_engulfing, "Bullish Harami": _bullish_harami,
    "Piercing Line": _piercing_line, "Tweezer Bottom": _tweezer_bottom,
}
BULLISH_3CANDLE = {
    "Three White Soldiers": _three_white_soldiers, "Three Inside Up": _three_inside_up,
    "Three Outside Up": _three_outside_up, "Morning Star": _morning_star,
}


def confirm_pattern(df: pd.DataFrame, direction: str):
    """
    direction: 'bearish' or 'bullish'.
    Checks the most recent candle(s) in df for ANY matching pattern of that
    direction (1-candle, 2-candle, 3-candle, and the 5-candle continuation
    pattern). Returns the pattern name on the first match found, else None.
    Order checked: 3-candle first (strongest signal), then 2-candle, then
    1-candle, then the 5-candle method pattern.
    """
    if len(df) < 1:
        return None
    rows = [_metrics(df.iloc[i]) for i in range(max(0, len(df) - 5), len(df))]
    last = rows[-1]

    if direction == "bearish":
        if len(rows) >= 3:
            a, b, c = rows[-3], rows[-2], rows[-1]
            for name, fn in BEARISH_3CANDLE.items():
                if fn(a, b, c):
                    return name
        if len(rows) >= 2:
            p, c = rows[-2], rows[-1]
            for name, fn in BEARISH_2CANDLE.items():
                if fn(p, c):
                    return name
        for name, fn in BEARISH_1CANDLE.items():
            if fn(last):
                return name
        if len(rows) >= 5 and _falling_three_method(rows[-5:]):
            return "Falling Three Method"
        return None

    elif direction == "bullish":
        if len(rows) >= 3:
            a, b, c = rows[-3], rows[-2], rows[-1]
            for name, fn in BULLISH_3CANDLE.items():
                if fn(a, b, c):
                    return name
        if len(rows) >= 2:
            p, c = rows[-2], rows[-1]
            for name, fn in BULLISH_2CANDLE.items():
                if fn(p, c):
                    return name
        for name, fn in BULLISH_1CANDLE.items():
            if fn(last):
                return name
        if len(rows) >= 5 and _rising_three_method(rows[-5:]):
            return "Rising Three Method"
        return None

    raise ValueError("direction must be 'bearish' or 'bullish'")
