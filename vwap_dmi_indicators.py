"""
Hand-rolled technical indicators for the VWAP/DMI Wednesday strategy
(REVISION 16, 2026-08-30). No third-party TA library -- pandas_ta is not
installed in this environment and isn't installable here either (no
matching PyPI distribution found when tried), which lines up with it being
a loosely-maintained package with known breakage on numpy>=2.0 (removed
np.NaN, which older pandas_ta releases reference directly). Everything
here is standard Wilder-smoothing math implemented directly in pandas,
same self-contained style as smc_confluence.py and contract_filters.py
elsewhere in this codebase -- no new dependency to break later.

All functions take a DataFrame with columns open/high/low/close/volume
(lowercase, matching the rest of this codebase's bar convention) and a
datetime index or begins_at column already parsed to datetime.
"""
import pandas as pd


def rolling_vwap(df: pd.DataFrame, window: int = 200, min_periods: int = 20) -> pd.Series:
    """Rolling `window`-bar VWAP: sum(typical_price * volume) / sum(volume)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical_price * df["volume"]
    rolling_tp_vol = tp_vol.rolling(window=window, min_periods=min_periods).sum()
    rolling_vol = df["volume"].rolling(window=window, min_periods=min_periods).sum()
    return rolling_tp_vol / rolling_vol


def _wilder_smooth(series: pd.Series, length: int) -> pd.Series:
    """Wilder's smoothing (the RMA used by ADX/DMI/ATR), approximated via
    an EWM with alpha=1/length, adjust=False -- the standard, widely-used
    approximation (including in most TA library implementations)."""
    return series.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average True Range, Wilder-smoothed."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return _wilder_smooth(tr, length)


def adx_dmi(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """Returns a DataFrame with columns adx, plus_di, minus_di."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_mask = (up_move > down_move) & (up_move > 0)
    minus_mask = (down_move > up_move) & (down_move > 0)
    plus_dm[plus_mask] = up_move[plus_mask]
    minus_dm[minus_mask] = down_move[minus_mask]

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    smoothed_tr = _wilder_smooth(tr, length)
    smoothed_plus_dm = _wilder_smooth(plus_dm, length)
    smoothed_minus_dm = _wilder_smooth(minus_dm, length)

    plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr)
    minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = _wilder_smooth(dx, length)

    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di})
