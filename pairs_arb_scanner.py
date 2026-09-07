"""
Pair-trading statistical-arbitrage scanner (REVISION 2, 2026-08-30), a third
strategy alongside the SMC volume bot (Mon/Tue/Thu/Fri) and the VWAP/DMI
trend screener (Wed) -- this one is proposed to run on Thursday ALONGSIDE
the SMC bot, per explicit user request ("both together").

REVISION 2 change (explicit user request, 2026-08-30): WATCHLIST_PAIRS is no
longer a hand-picked 6-pair list. discover_candidate_pairs() now auto-
generates candidates from the same live scan-generated universe the VWAP/DMI
screener uses (watchlist_universe.json, ~399 symbols) -- a two-stage funnel:
a cheap, vectorized correlation pre-filter across every possible combination
in the universe (~79,000 pairs at 399 symbols, one pandas .corr() call, not
79,000 regressions), then only the pairs that clear the correlation bar get
the expensive cointegration test in scan_pairs(), same "let it all pass
through and whatever clears the gate, clears it" principle as every other
AND-gate in this pipeline. Real index-level instruments (SPX, NDX, VIX, etc)
are NOT included -- Robinhood only exposes 17 total index instruments, most
of them either crypto real-time indices or cash-settled index options that
would need a second, not-yet-built contract-resolution path (different
settlement mechanics than the equity-option pipeline contract_selector
already handles). Index-level exposure instead comes from SPY/QQQ/DIA/IWM,
which already flow through the existing pipeline end-to-end and are already
in the 399-symbol universe. The fixed 6-pair FALLBACK_WATCHLIST_PAIRS below
is kept only as a safety net for a small staged dataset (e.g. a quick
dry run), not the production path.

Same architecture discipline as every other script in this pipeline:
  - Consumes only pre-staged Robinhood historicals (get_equity_historicals),
    NOT yfinance -- the user's original sketch used yfinance; this version
    doesn't, matching how every other strategy here already avoids
    unofficial/scraped data sources.
  - SIGNAL-ONLY (this module). This scanner still only detects and logs a
    candidate pair signal -- it does not write to pending_live_orders.json,
    resolve a real option contract, run live_risk_checks.py, or call any
    broker/order tool. Turning a hit into an actual two-leg proposal is now
    a separate, SEPARATE-BUT-BUILT step: see REVISION 4 below.
  - Per the user's explicit choice: a live pairs trade would count as the
    ONE allowed open position (both legs together), budget split 50/50
    across the two legs, dynamically sized off real buying power via
    get_max_contract_budget() -- NOT the hardcoded $177 in the original
    sketch.

Why no statsmodels: this sandbox's pip mirror does not have statsmodels or
patsy available (confirmed by direct install attempt), so the cointegration
step below is a from-scratch numpy/pandas implementation rather than
statsmodels.tsa.stattools.coint():
  - hedge ratio: OLS via numpy.linalg.lstsq (series_a ~ const + beta*series_b)
  - cointegration test: a single-lag (non-augmented) Dickey-Fuller test on
    the regression residuals (spread), computed directly from OLS on
    Δspread_t ~ spread_{t-1} (no constant, since the spread is already
    ~zero-mean by construction of the cointegrating regression).
    The reported "p_value" is a linear interpolation against standard
    asymptotic Dickey-Fuller "no constant" critical values (Fuller 1976 /
    MacKinnon 1994 quantiles) -- an approximation of, not identical to,
    statsmodels' MacKinnon response-surface p-value. It is a simplified,
    single-lag ADF (no augmentation lags), which is a reasonable but not
    exhaustive test for hourly-bar spreads over a ~60-90 session window.
    This is disclosed here rather than silently claimed to be textbook-exact.

REVISION 5 (2026-09-07, INTRADAY REBUILD, per explicit user request) --
this scanner is now the INTRADAY TIER of a two-tier design (see
docs/ENTRY_SPEC.md section 3 and pairs_daily_tier.py):

  * pairs_daily_tier.py runs ONCE near the open: correlation + cointegration
    on HOURLY bars over ~60-90 sessions -> writes pairs_today.json with the
    day's qualified pairs, each with a FIXED hedge ratio.
  * this file, run every 15 min, reads pairs_today.json and checks each
    pair's rolling z-score over 60 x 5-MINUTE bars using that fixed hedge
    ratio (calculate_zscore(..., hedge_ratio=beta)). Entry at |z| >= 2.0.
    No cointegration re-check -- the daily tier already did it.
    See scan_pairs_intraday().

The legacy all-in-one path (discover_candidate_pairs + scan_pairs, both on
one hourly dataset) is kept for backtests and as the fallback when
pairs_today.json is absent.

Entry rule: |z-score| >= 2.0 on a 60-bar rolling window of the spread. In
the intraday tier the 60 bars are 5-minute bars and the hedge ratio is
fixed by the daily tier; in the legacy path the 60 bars are whatever was
staged and the hedge ratio is re-fit, gated by cointegration p < 0.10.

Usage:
  python3 pairs_arb_scanner.py <5min_bars.json> [--now-ts ISO8601]
      -> intraday tier if pairs_today.json exists, else legacy scan
  python3 pairs_daily_tier.py <hourly_bars.json>   -> writes pairs_today.json
"""
import json, sys, os
from datetime import datetime, timezone
import numpy as np
import pandas as pd

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BACKTEST_DIR, "pairs_arb_log.jsonl")

FALLBACK_WATCHLIST_PAIRS = [
    ("AMD", "NVDA"),
    ("COIN", "MARA"),
    ("SPY", "QQQ"),
    ("F", "GM"),
    ("XLE", "XOM"),
    ("SOFI", "HOOD"),
]

Z_WINDOW = 60
Z_ENTRY = 2.0
COINT_P_MAX = 0.10

# INTRADAY REBUILD (2026-09-07): the intraday tier reads the day's qualified
# pairs + fixed hedge ratios from here (written by pairs_daily_tier.py).
PAIRS_TODAY_FILE = os.path.join(BACKTEST_DIR, "pairs_today.json")
# Intraday-tier z-score runs on 5-minute bars; 60 bars ~= 5 hours.
Z_WINDOW_5MIN = 60
MIN_5MIN_BARS = Z_WINDOW_5MIN + 5

# Auto-discovery of candidate pairs from a wide universe (REVISION 2).
CORR_WINDOW = 250          # bars used for the correlation pre-filter
CORR_THRESHOLD = 0.80      # |corr| must clear this to earn a full cointegration test
MAX_CANDIDATE_PAIRS = 400  # cap on pairs that go on to the (expensive) cointegration test

UNIVERSE_FILE = os.path.join(BACKTEST_DIR, "watchlist_universe.json")

# REVISION 3 (2026-08-31), per explicit user request -- small-account capital
# sizing for WHENEVER this strategy is wired up live (still signal-only as of
# this revision; see module docstring). Supersedes the "50/50 split of
# get_max_contract_budget()" description above: because a pairs trade is two
# option legs at once (long call on leg A + long put on leg B, or vice versa)
# rather than one, capping it as a even split of the SAME 25%-of-buying-power
# single-leg budget used by SMC/VWAP-DMI would size it too aggressively (two
# legs, each up to the full single-trade budget). Instead each leg gets its
# own smaller fixed cap, and the pair is rejected outright if the combined
# cost of both legs would exceed the package cap -- see
# check_pairs_affordability() below, the two-leg analogue of
# live_risk_checks.check_affordability().
MAX_LEG_PREMIUM = 20.00       # per leg, total cost = ask * 100 -- standalone-test default only, see REVISION 4
MAX_PACKAGE_PREMIUM = 40.00   # both legs combined -- standalone-test default only, see REVISION 4

# REVISION 4 (2026-08-31), per the user's own "Native Robinhood Engine 3
# Pipeline" sketch (pairs_pipeline.py) -- this is the completion of the
# live order-prep path this module's docstring described as "not yet
# built." Two new files, NOT this one, do the actual work:
#   resolve_pairs_leg.py   -- picks one leg's contract from a pre-fetched
#                              candidate list (highest open interest within
#                              a price window), pure Python, no tool access.
#   pairs_prepare_order.py -- runs the combined two-leg risk gate and, if it
#                              passes, appends ONE package proposal to the
#                              SHARED pending_live_orders.json (same file
#                              SMC/VWAP-DMI write to) for human confirmation.
# This module (pairs_arb_scanner.py) is unchanged in what it does -- it
# still only detects and logs signals (scan_pairs()/log_hits() below). The
# calling trigger session is what strings these three pieces together: run
# this scanner -> on a hit, fetch each leg's option chain via the real MCP
# tools -> resolve_pairs_leg.py x2 -> pairs_prepare_order.py.
#
# Three corrections made versus the user's literal sketch, each explained
# in full in pairs_prepare_order.py's own docstring (not repeated here):
#   1. No rh_client Python object -- the calling trigger session makes the
#      real mcp__RBH__get_option_chains/get_option_instruments/
#      get_option_quotes calls itself, same as every other strategy here.
#   2. The $42.50 package / $21.25 per-leg budget in the sketch was a
#      SNAPSHOT of 25% of the ~$170 account on the day it was written, not
#      a live calculation -- pairs_prepare_order.py instead calls
#      live_risk_checks.get_max_contract_budget(buying_power, vix) (the
#      exact function SMC/VWAP already use) and splits the result 50/50,
#      so the number stays correct as the account grows or shrinks and
#      inherits VIX-regime sizing for free. It matches the sketch's numbers
#      today only because the account happens to be ~$170 today.
#   3. The sketch's `json.dump([trade_proposal], f)` would have silently
#      overwritten pending_live_orders.json, destroying any pending SMC or
#      VWAP/DMI proposal already in that shared file.
#      pairs_prepare_order.py appends instead, exactly like
#      live_prepare_order.py does for the single-leg strategies.


def check_pairs_affordability(leg_a_ask, leg_b_ask,
                               max_leg_premium=MAX_LEG_PREMIUM,
                               max_package_premium=MAX_PACKAGE_PREMIUM):
    """Two-leg analogue of live_risk_checks.check_affordability(). As of
    REVISION 4 below this IS called by a live pipeline -- pairs_prepare_order.py
    calls it with DYNAMIC max_leg_premium/max_package_premium (half/all of
    get_max_contract_budget(buying_power, vix), not the MAX_LEG_PREMIUM/
    MAX_PACKAGE_PREMIUM module constants above) -- those constants remain
    only as this function's standalone-testing defaults.
    leg_a_ask/leg_b_ask are per-contract (per-share) premiums; each leg's
    total cost is ask * 100. Returns (ok, note, leg_a_cost, leg_b_cost)."""
    leg_a_cost = leg_a_ask * 100
    leg_b_cost = leg_b_ask * 100
    package_cost = leg_a_cost + leg_b_cost
    leg_a_ok = leg_a_cost <= max_leg_premium
    leg_b_ok = leg_b_cost <= max_leg_premium
    package_ok = package_cost <= max_package_premium
    ok = leg_a_ok and leg_b_ok and package_ok
    note = (f"leg A ${leg_a_cost:.2f} ({'<=' if leg_a_ok else '>'} ${max_leg_premium:.2f}), "
            f"leg B ${leg_b_cost:.2f} ({'<=' if leg_b_ok else '>'} ${max_leg_premium:.2f}), "
            f"package ${package_cost:.2f} ({'<=' if package_ok else '>'} ${max_package_premium:.2f})")
    return ok, note, leg_a_cost, leg_b_cost


def load_universe(path: str = UNIVERSE_FILE, fallback=None) -> list:
    """Same live scan-generated universe as vwap_dmi_screener.py's
    load_universe() -- both strategies draw candidates from one shared,
    dynamically-generated pool rather than each keeping its own hand list."""
    try:
        with open(path) as f:
            data = json.load(f)
        tickers = data.get("tickers", [])
        if tickers:
            return tickers
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    fb = fallback if fallback is not None else FALLBACK_WATCHLIST_PAIRS
    return sorted({sym for pair in fb for sym in pair})

# Asymptotic Dickey-Fuller critical values, "no constant" case (Fuller 1976 /
# MacKinnon 1994 quantiles), used to interpolate an approximate p-value from
# the ADF t-statistic. Table is (t_stat, right-tail probability of a value
# this negative or more under the unit-root null), sorted ascending by t_stat.
_DF_NC_TABLE = [
    (-2.66, 0.01), (-2.26, 0.025), (-1.95, 0.05), (-1.60, 0.10),
    (-1.28, 0.20), (-0.80, 0.40), (0.0, 0.60), (0.92, 0.90),
]


def _approx_adf_pvalue(t_stat: float) -> float:
    """Linear interpolation of an approximate ADF p-value from the table
    above. Values outside the tabulated range are clamped to the nearest
    endpoint probability rather than extrapolated."""
    xs = [row[0] for row in _DF_NC_TABLE]
    ps = [row[1] for row in _DF_NC_TABLE]
    if t_stat <= xs[0]:
        return ps[0]
    if t_stat >= xs[-1]:
        return ps[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= t_stat <= xs[i + 1]:
            frac = (t_stat - xs[i]) / (xs[i + 1] - xs[i])
            return ps[i] + frac * (ps[i + 1] - ps[i])
    return 1.0


def check_cointegration(series_a: np.ndarray, series_b: np.ndarray):
    """OLS hedge ratio + single-lag Dickey-Fuller test on the residual
    spread. Returns (p_value_approx, hedge_ratio, adf_t_stat).

    FIX (2026-09-07): the ADF residual now subtracts the OLS INTERCEPT too
    (`series_a - intercept - hedge_ratio * series_b`), so it is genuinely
    zero-mean -- which is the assumption the "no constant" DF critical-value
    table below relies on. Before this fix the residual still carried the
    intercept (a non-zero level), which biased gamma_hat toward zero and
    made check_cointegration reject almost nothing (a stationary AR(1)
    spread with phi=0.6 scored p~0.41). calculate_zscore is unaffected --
    its rolling mean removes any level regardless.
    """
    X = np.column_stack([np.ones(len(series_b)), series_b])
    beta, *_ = np.linalg.lstsq(X, series_a, rcond=None)
    intercept, hedge_ratio = beta[0], beta[1]
    spread = series_a - intercept - hedge_ratio * series_b

    y = spread
    y_lag = y[:-1]
    dy = y[1:] - y[:-1]
    denom = float(np.sum(y_lag ** 2))
    if denom == 0:
        return 1.0, float(hedge_ratio), 0.0
    gamma_hat = float(np.sum(y_lag * dy) / denom)
    resid = dy - gamma_hat * y_lag
    n = len(y_lag)
    if n < 3:
        return 1.0, float(hedge_ratio), 0.0
    sigma2 = float(np.sum(resid ** 2) / (n - 1))
    se = np.sqrt(sigma2 / denom) if denom > 0 else np.nan
    t_stat = gamma_hat / se if se and not np.isnan(se) and se > 0 else 0.0
    p_value = _approx_adf_pvalue(t_stat)
    return p_value, float(hedge_ratio), float(t_stat)


def calculate_zscore(series_a: pd.Series, series_b: pd.Series, window: int = Z_WINDOW,
                      hedge_ratio: float = None):
    """Rolling z-score of the spread (series_a - hedge_ratio * series_b).

    hedge_ratio: if given (INTRADAY TIER -- the fixed beta from
    pairs_today.json), it is used as-is. If None (legacy all-in-one path),
    beta is re-fit by OLS on the supplied window.
    """
    if hedge_ratio is None:
        X = np.column_stack([np.ones(len(series_b)), series_b.values])
        beta, *_ = np.linalg.lstsq(X, series_a.values, rcond=None)
        hedge_ratio = float(beta[1])
    spread = series_a - hedge_ratio * series_b
    rolling_mean = spread.rolling(window=window).mean()
    rolling_std = spread.rolling(window=window).std()
    z_score = (spread - rolling_mean) / rolling_std
    return z_score, float(hedge_ratio), float(spread.iloc[-1])


def _load_series(bars_by_symbol: dict, symbol: str, now_ts: str = None) -> pd.Series:
    bars = bars_by_symbol.get(symbol, [])
    if now_ts:
        bars = [b for b in bars if b["begins_at"] <= now_ts]
    if not bars:
        return pd.Series(dtype=float)
    df = pd.DataFrame(bars)
    df["begins_at"] = pd.to_datetime(df["begins_at"])
    df["close"] = df["close_price"].astype(float)
    df = df.drop_duplicates(subset="begins_at").sort_values("begins_at").reset_index(drop=True)
    return pd.Series(df["close"].values, index=df["begins_at"], name=symbol)


def discover_candidate_pairs(bars_by_symbol: dict, universe: list = None, now_ts: str = None,
                              corr_window: int = CORR_WINDOW, corr_threshold: float = CORR_THRESHOLD,
                              max_pairs: int = MAX_CANDIDATE_PAIRS) -> list:
    """Auto-discovers candidate pairs from a symbol universe instead of a
    hand-picked list. Stage 1 (this function): a cheap, vectorized
    correlation pre-filter -- one pandas .corr() call across every symbol
    that has enough history, not a per-pair loop. Stage 2 (scan_pairs, via
    check_cointegration): the expensive OLS+ADF cointegration test, run only
    on the pairs that clear corr_threshold here. Returns (ticker_a, ticker_b)
    tuples sorted by |correlation| descending, capped at max_pairs so the
    cointegration stage stays bounded even at a ~400-symbol universe
    (~79,000 possible combinations)."""
    universe = universe or list(bars_by_symbol.keys())
    price_cols = {}
    for sym in universe:
        s = _load_series(bars_by_symbol, sym, now_ts)
        if len(s) >= corr_window:
            price_cols[sym] = s.iloc[-corr_window:].reset_index(drop=True)
    if len(price_cols) < 2:
        return []
    price_df = pd.DataFrame(price_cols)
    corr = price_df.corr()
    symbols = list(price_df.columns)
    scored = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            c = corr.iloc[i, j]
            if pd.notna(c) and abs(c) >= corr_threshold:
                scored.append((symbols[i], symbols[j], abs(float(c))))
    scored.sort(key=lambda t: t[2], reverse=True)
    return [(a, b) for a, b, _ in scored[:max_pairs]]


def scan_pairs(bars_by_symbol: dict, now_ts: str = None, buying_power: float = None,
                pairs: list = None, universe: list = None) -> list:
    if pairs is None:
        universe = universe or load_universe()
        if len(universe) > 20:
            pairs = discover_candidate_pairs(bars_by_symbol, universe, now_ts=now_ts)
        else:
            pairs = FALLBACK_WATCHLIST_PAIRS
    proposals = []
    for ticker_a, ticker_b in pairs:
        sa = _load_series(bars_by_symbol, ticker_a, now_ts)
        sb = _load_series(bars_by_symbol, ticker_b, now_ts)
        df = pd.concat([sa, sb], axis=1, join="inner").dropna()
        if len(df) < Z_WINDOW + 5:
            continue
        series_a, series_b = df[ticker_a], df[ticker_b]

        p_value, hedge_ratio_c, adf_t = check_cointegration(series_a.values, series_b.values)
        z_scores, hedge_ratio, current_spread = calculate_zscore(series_a, series_b, window=Z_WINDOW)
        current_z = z_scores.iloc[-1]
        if pd.isna(current_z):
            continue

        signal = None
        if current_z <= -Z_ENTRY:
            signal = {
                "strategy": "PAIRS_STAT_ARB_MEAN_REVERSION",
                "pair": f"{ticker_a}/{ticker_b}",
                "direction": "LONG_A_SHORT_B",
                "leg_1_call_candidate": ticker_a,
                "leg_2_put_candidate": ticker_b,
            }
        elif current_z >= Z_ENTRY:
            signal = {
                "strategy": "PAIRS_STAT_ARB_MEAN_REVERSION",
                "pair": f"{ticker_a}/{ticker_b}",
                "direction": "SHORT_A_LONG_B",
                "leg_1_put_candidate": ticker_a,
                "leg_2_call_candidate": ticker_b,
            }

        if signal and p_value < COINT_P_MAX:
            signal.update({
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "as_of_bar": str(df.index[-1]),
                "z_score": round(float(current_z), 2),
                "adf_p_value_approx": round(float(p_value), 4),
                "adf_t_stat": round(float(adf_t), 3),
                "hedge_ratio": round(float(hedge_ratio), 4),
                "price_a": round(float(series_a.iloc[-1]), 2),
                "price_b": round(float(series_b.iloc[-1]), 2),
                "target_exit": "Z_SCORE = 0.0",
                "stop_loss": "Z_SCORE = +/-3.5",
            })
            if buying_power is not None:
                alloc_per_leg = round((buying_power * 0.85) / 2, 2)
                signal["allocation_per_leg_reference"] = alloc_per_leg
            proposals.append(signal)
    return proposals


def _pairs_today_from_git():
    """Scheduled firings share no filesystem, so the daily tier commits
    pairs_today.json to the repo (pairs_daily_tier.py --commit) and the
    intraday tier reads it straight out of git -- `git show
    origin/main:pairs_today.json` -- without disturbing its own pinned
    checkout. The task prompt should `git fetch origin main` first."""
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    for ref in ("origin/main", "origin/HEAD", "HEAD"):
        try:
            out = subprocess.run(["git", "-C", here, "show", f"{ref}:pairs_today.json"],
                                 capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                payload = json.loads(out.stdout)
                if payload.get("pairs") is not None:
                    return payload
        except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            continue
    return None


def load_pairs_today(path: str = PAIRS_TODAY_FILE):
    """Returns the pairs_today payload (from pairs_daily_tier.py), or None.
    Tries a local file first (dry runs / same-container tests), then reads
    the committed copy out of git (the live path -- see _pairs_today_from_git).
    None -> the caller falls back to the legacy all-in-one scan_pairs()."""
    try:
        with open(path) as f:
            payload = json.load(f)
        if payload.get("pairs") is not None:
            return payload
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _pairs_today_from_git()


def scan_pairs_intraday(bars_by_symbol: dict, pairs_today: dict, now_ts: str = None,
                         buying_power: float = None) -> list:
    """INTRADAY TIER. For each pair the daily tier qualified this morning,
    compute the spread with that pair's FIXED hedge ratio and a rolling
    z-score over Z_WINDOW_5MIN 5-minute bars, and trigger an entry at
    |z| >= Z_ENTRY. No cointegration re-check here -- the pair already
    cleared p < COINT_P_MAX in pairs_daily_tier.py.

    bars_by_symbol: {symbol: [5-minute bar dicts]}.
    """
    proposals = []
    for entry in pairs_today.get("pairs", []):
        ticker_a, ticker_b = entry["ticker_a"], entry["ticker_b"]
        beta = float(entry["hedge_ratio"])

        sa = _load_series(bars_by_symbol, ticker_a, now_ts)
        sb = _load_series(bars_by_symbol, ticker_b, now_ts)
        df = pd.concat([sa, sb], axis=1, join="inner").dropna()
        if len(df) < MIN_5MIN_BARS:
            continue
        series_a, series_b = df[ticker_a], df[ticker_b]

        z_scores, _, current_spread = calculate_zscore(
            series_a, series_b, window=Z_WINDOW_5MIN, hedge_ratio=beta)
        current_z = z_scores.iloc[-1]
        if pd.isna(current_z):
            continue

        signal = None
        if current_z <= -Z_ENTRY:
            signal = {
                "strategy": "PAIRS_STAT_ARB_MEAN_REVERSION",
                "pair": f"{ticker_a}/{ticker_b}",
                "direction": "LONG_A_SHORT_B",
                "leg_1_call_candidate": ticker_a,
                "leg_2_put_candidate": ticker_b,
            }
        elif current_z >= Z_ENTRY:
            signal = {
                "strategy": "PAIRS_STAT_ARB_MEAN_REVERSION",
                "pair": f"{ticker_a}/{ticker_b}",
                "direction": "SHORT_A_LONG_B",
                "leg_1_put_candidate": ticker_a,
                "leg_2_call_candidate": ticker_b,
            }
        if not signal:
            continue

        signal.update({
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "tier": "intraday_5min",
            "as_of_bar": str(df.index[-1]),
            "z_score": round(float(current_z), 2),
            "z_window_bars": Z_WINDOW_5MIN,
            "hedge_ratio": round(beta, 4),
            "hedge_ratio_source": "pairs_today.json daily tier",
            "adf_p_value_approx": entry.get("adf_p_value"),
            "session_date": pairs_today.get("session_date"),
            "price_a": round(float(series_a.iloc[-1]), 2),
            "price_b": round(float(series_b.iloc[-1]), 2),
            "target_exit": "Z_SCORE = 0.0",
            "stop_loss": "Z_SCORE = +/-3.5",
        })
        if buying_power is not None:
            signal["allocation_per_leg_reference"] = round((buying_power * 0.85) / 2, 2)
        proposals.append(signal)
    return proposals


def log_hits(hits):
    if not hits:
        return
    with open(LOG_PATH, "a") as f:
        for h in hits:
            f.write(json.dumps(h) + "\n")


if __name__ == "__main__":
    bars_path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else "pairs_5min_bars.json"
    now_ts = None
    if "--now-ts" in sys.argv:
        now_ts = sys.argv[sys.argv.index("--now-ts") + 1]

    with open(bars_path) as f:
        bars_by_symbol = json.load(f)

    pairs_today = load_pairs_today()

    if pairs_today is not None:
        print(f"=== Pairs StatArb -- INTRADAY TIER @ {datetime.now(timezone.utc).isoformat()} "
              f"(as-of {now_ts or 'latest available'}) ===")
        print(f"pairs_today.json: session {pairs_today.get('session_date')}, "
              f"{len(pairs_today['pairs'])} qualified pair(s), "
              f"z-window={Z_WINDOW_5MIN} x 5-min bars, entry |z|>={Z_ENTRY}\n")
        hits = scan_pairs_intraday(bars_by_symbol, pairs_today, now_ts=now_ts)
    else:
        universe = load_universe()
        universe = [s for s in universe if s in bars_by_symbol] or list(bars_by_symbol.keys())
        print(f"=== Pairs StatArb -- LEGACY all-in-one (no pairs_today.json) @ "
              f"{datetime.now(timezone.utc).isoformat()} (as-of {now_ts or 'latest available'}) ===")
        print(f"Universe: {len(universe)} symbols")
        candidate_pairs = discover_candidate_pairs(bars_by_symbol, universe, now_ts=now_ts) \
            if len(universe) > 20 else FALLBACK_WATCHLIST_PAIRS
        print(f"Correlation pre-filter (window={CORR_WINDOW}, |corr|>={CORR_THRESHOLD}): "
              f"{len(candidate_pairs)} candidate pair(s)")
        print(f"z-window={Z_WINDOW}, entry |z|>={Z_ENTRY}, cointegration approx-p<{COINT_P_MAX}\n")
        hits = scan_pairs(bars_by_symbol, now_ts=now_ts, pairs=candidate_pairs)

    log_hits(hits)

    if hits:
        print(f"*** {len(hits)} qualifying pair signal(s) ***")
        print(json.dumps(hits, indent=2))
    else:
        print("No pairs currently exceed the |Z| >= 2.0 threshold.")

    print("\nSIGNAL-ONLY -- no order-placement tool was called or is reachable from this script.")
