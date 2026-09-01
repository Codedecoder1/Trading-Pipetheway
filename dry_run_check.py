"""
Live dry-run signal check -- SIGNAL-ONLY, read-only.

REVISION 15 (2026-08-30): the stock side of the universe is now DYNAMIC,
sourced live each cycle from a saved Robinhood scanner ("SMC Bot - Live
Movers Gate", scan_id 96f10af3-ee65-497b-9dcd-40ebdb84e83d -- run via
mcp__RBH__run_scan by the calling/orchestrating session, same as every
other MCP call in this pipeline). That scan already screens the ENTIRE
optionable stock market for: instrument_type=STOCK, Last price >= $10,
30-day average volume >= 1.5M shares, and % change from prior close OUTSIDE
[-2.7%, +2.7%] -- i.e. it does the liquidity pre-filter AND the Stage-1
mover screen natively, live, with no static symbol list to maintain and no
per-cycle historicals fetch for names that were never going to qualify.
This replaced an earlier proposal to hand-roll a 1,000-symbol static list
via runtime Wikipedia scraping (rejected 2026-08-30 for the same reason the
original fake-external-API universe proposal was rejected on 2026-08-28:
an unofficial data source fetched live inside the trading pipeline, with a
silent-fallback failure mode -- Robinhood's own scanner tools avoid all of
that, same as the two saved sanity-check scans already in bot_runbook.md).

The calling session passes the scan's resulting tickers here via
DRY_RUN_LIVE_UNIVERSE_PATH (see below) unioned with MAJOR_ETFS from
index_universe.py (12 explicitly-curated ETFs -- SPY/QQQ/IWM/DIA sector
SPDRs SMH/XLF/XLE/XBI, and leveraged TQQQ/SQQQ/SOXL/LABU -- kept as an
explicit list rather than folded into the scanner's ANY_OF[STOCK,ETF]
filter, because that pulled in liquid-but-irrelevant ETFs like bond funds;
the scanner is STOCK-only). ETFs still get the same abs(mover_pct)>=2.7%
recheck below as everything else, so an ETF that isn't actually moving this
cycle is filtered out same as before -- only now that recheck is against
this cycle's live bars rather than a big static list.

If DRY_RUN_LIVE_UNIVERSE_PATH is missing (e.g. manual backtest/dry-run
invocation, not a live trigger firing), this script falls back to the old
static universe (Dow-30 + S&P-500-top-30 + Nasdaq-30 + Nasdaq-100/QQQ +
S&P-100 + Russell-Top-100 + PHLX-Semiconductor-top-20 + KBW-Bank +
S&P-500-top-200 + MAJOR_ETFS, deduped -- see index_universe.py) so existing
backtest/manual workflows are unaffected. CHRONIC_MOVERS is kept only for
that fallback path -- the live scanner path has no static list to exclude
names from in the first place, so the "chronic mover" concept doesn't apply
there; a symbol that whipsaws a lot just shows up via the scan like anything
else, same live scrutiny as every other name.

Pulls prev-day close + today's regular-session 5-minute bars so far for
this cycle's universe (however it was resolved above), recomputes the
>=2.7% mover screen on the LATEST bar for each symbol (a cheap safety net --
the live scanner path already enforced this, but bars can move between scan
time and this check), and for any symbol currently over threshold runs the
same walk-forward confluence detector (STRICT/LOOSE x 5min/10min/30min)
used throughout backtesting, evaluated at the current moment only (this
script is meant to be re-run on a schedule during market hours, so
"walk-forward across time" happens naturally across separate invocations
rather than inside one run).

Any raw confluence hit is then run through the exact same Layer 1 gate as
production (contract_filters.check_volume_impulse / check_vwap_alignment /
check_session_time -- REVISION 8, fail-closed AND gate). Layer-1-passing
signals are appended to dry_run_log.jsonl (append-only, persists across
scheduled runs) and printed in the final summary so a scheduled task's
run-completion notification carries the result.

HARD RULE: this script calls ONLY read/query tools (get_equity_historicals
via the wrapper below). It NEVER calls place_option_order, review_option_order,
place_equity_order, or review_equity_order, and never will regardless of
what this run finds. That is enforced by this script simply not importing
or referencing any such capability -- there is nothing here that could
place a trade even if the numbers looked perfect.

This script does not fetch data itself (no direct broker/API client is
wired into this pure-Python file) -- it expects one JSON blob per batched
get_equity_historicals response, already fetched by the calling agent/session
and written to disk, under RAW_DIR (see RAW_DIR below), plus (new in
REVISION 15) the live universe list itself at DRY_RUN_LIVE_UNIVERSE_PATH,
also written by the calling session after it runs the scan. This mirrors
exactly how Stage B fetching worked throughout backtesting: every MCP tool
call (run_scan included) happens at the orchestrating-session level -- this
script is the evaluation engine, not the fetch layer.
"""
import json, sys, os
from datetime import datetime, timezone
import pandas as pd

sys.path.insert(0, '/home/claude/smc_bot')
from smc_confluence import detect_confluence_signal
from contract_filters import check_volume_impulse, check_vwap_alignment, check_session_time, VERSION_LABEL
from index_universe import get_universe, MAJOR_ETFS

CHRONIC_MOVERS = set()  # was {"AMAT", "LRCX", "AMD", "MU", "ADBE", "CRM", "ORCL", "TSLA"} -- see module docstring, 2026-08-28. Only applies to the static-universe fallback path (no live scan file).

LIVE_UNIVERSE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dry_run_live_universe.json')

def _resolve_universe():
    """REVISION 15: prefer the live scanner-derived universe (written by the
    calling session as a JSON array of tickers at LIVE_UNIVERSE_PATH,
    already unioned with MAJOR_ETFS by that caller). Falls back to the old
    static full-index universe when that file is absent, e.g. for manual
    backtest/dry-run invocations outside the live trigger flow."""
    if os.path.exists(LIVE_UNIVERSE_PATH):
        with open(LIVE_UNIVERSE_PATH) as f:
            live_syms = json.load(f)
        # Defensive union with MAJOR_ETFS even if the caller forgot -- cheap and correct either way.
        return sorted(set(live_syms) | set(MAJOR_ETFS)), True
    return sorted(set(get_universe(dedup=True)) - CHRONIC_MOVERS), False

UNIVERSE, USING_LIVE_SCAN_UNIVERSE = _resolve_universe()

MOVER_THRESH = 2.7
CONFIGS = [("STRICT", 0.015), ("LOOSE", 0.006)]
INTERVAL_SPECS = [("5min", "5min", 36), ("10min", "10min", 18), ("30min", "30min", 6)]

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
LOG_PATH = os.path.join(BACKTEST_DIR, 'dry_run_log.jsonl')


def evaluate(prev_close_by_symbol, intraday_bars_by_symbol, now_ts=None):
    """
    prev_close_by_symbol: {symbol: float}
    intraday_bars_by_symbol: {symbol: [bar_dict, ...]} -- today's 5-minute
        regular-session bars so far, each bar_dict shaped like the raw
        get_equity_historicals bar (open_price/close_price/high_price/
        low_price/volume/begins_at as strings, same as every other script
        in this backtest).
    now_ts: pandas.Timestamp to use as "now" for session_time evaluation;
        defaults to the timestamp of each symbol's last available bar.

    Returns list of Layer-1-passing signal dicts (same shape as the
    Stage C/D pipeline used throughout backtesting) found in THIS pass.
    """
    hits = []
    for sym in UNIVERSE:
        prev_close = prev_close_by_symbol.get(sym)
        bars = intraday_bars_by_symbol.get(sym)
        if not prev_close or not bars:
            continue

        df5 = pd.DataFrame(bars)
        df5 = df5.rename(columns={"open_price": "open", "close_price": "close",
                                   "high_price": "high", "low_price": "low"})
        for col in ["open", "close", "high", "low"]:
            df5[col] = df5[col].astype(float)
        df5["volume"] = df5["volume"].astype(float)
        df5["begins_at"] = pd.to_datetime(df5["begins_at"])
        df5 = df5.sort_values("begins_at").reset_index(drop=True)
        if df5.empty:
            continue

        last_close = float(df5.iloc[-1]["close"])
        ts = df5.iloc[-1]["begins_at"] if now_ts is None else now_ts
        mover_pct = (last_close - prev_close) / prev_close * 100
        if abs(mover_pct) < MOVER_THRESH:
            continue

        df5i = df5.set_index("begins_at")
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        frames = {
            "5min": df5.reset_index(drop=True),
            "10min": df5i.resample("10min").agg(agg).dropna().reset_index(),
            "30min": df5i.resample("30min").agg(agg).dropna().reset_index(),
        }

        for label, key, cbars in INTERVAL_SPECS:
            df = frames[key]
            need = cbars + 2
            if len(df) < need:
                continue
            for cfg_label, thresh in CONFIGS:
                sig, poc, pat = detect_confluence_signal(df, consolidation_bars=cbars, threshold_pct=thresh)
                if sig not in ("BULLISH_CONFLUENCE", "BEARISH_CONFLUENCE"):
                    continue
                direction = "call" if sig == "BULLISH_CONFLUENCE" else "put"

                # Layer 1: volume impulse + VWAP + session time, identical to production.
                up_to_interval = df
                signal_bar_volume = float(up_to_interval["volume"].iloc[-1])
                recent_bar_volumes = [float(v) for v in up_to_interval["volume"].iloc[:-1].tolist()]
                typical = (df5["high"] + df5["low"] + df5["close"]) / 3.0
                vwap = (float((typical * df5["volume"]).sum() / df5["volume"].sum())
                        if df5["volume"].sum() > 0 else last_close)

                vi_ok, vi_note = check_volume_impulse(signal_bar_volume, recent_bar_volumes)
                vwap_ok, vwap_note = check_vwap_alignment(last_close, vwap, direction)
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S+00:00") if hasattr(ts, "strftime") else str(ts)
                session_ok, session_note = check_session_time(ts_str)
                layer1_passed = vi_ok and vwap_ok and session_ok

                record = {
                    "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                    "symbol": sym, "direction": direction, "signal": sig,
                    "interval": label, "config": cfg_label, "timestamp": ts_str,
                    "entry_price": last_close, "mover_pct": round(mover_pct, 2),
                    "poc": poc, "pattern": pat,
                    "layer1_passed": layer1_passed,
                    "checks": {
                        "volume_impulse": {"ok": vi_ok, "note": vi_note},
                        "vwap": {"ok": vwap_ok, "note": vwap_note},
                        "session_time": {"ok": session_ok, "note": session_note},
                    },
                }
                if layer1_passed:
                    hits.append(record)
    return hits


def log_hits(hits):
    if not hits:
        return
    with open(LOG_PATH, 'a') as f:
        for h in hits:
            f.write(json.dumps(h) + "\n")


if __name__ == "__main__":
    # Expects two JSON files staged by the calling session (see module
    # docstring): PREV_CLOSE_PATH -> {symbol: prev_close}, TODAY_BARS_PATH
    # -> {symbol: [bar, ...]}. Paths can be overridden via argv for
    # backtest-mode dry-runs against a past date.
    prev_close_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BACKTEST_DIR, 'dryrun_prev_close.json')
    today_bars_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BACKTEST_DIR, 'dryrun_today_bars.json')

    with open(prev_close_path) as f:
        prev_close_by_symbol = json.load(f)
    with open(today_bars_path) as f:
        intraday_bars_by_symbol = json.load(f)

    print(f'=== "{VERSION_LABEL}" DRY-RUN check @ {datetime.now(timezone.utc).isoformat()} ===')
    if USING_LIVE_SCAN_UNIVERSE:
        print(f"Universe: {len(UNIVERSE)} symbols (LIVE -- Robinhood scanner movers + {len(MAJOR_ETFS)} curated ETFs, REVISION 15)")
    else:
        print(f"Universe: {len(UNIVERSE)} symbols (STATIC FALLBACK -- full index universe minus chronic movers; no {os.path.basename(LIVE_UNIVERSE_PATH)} found)")
    print(f"Symbols with data this pass: {len(intraday_bars_by_symbol)}")

    hits = evaluate(prev_close_by_symbol, intraday_bars_by_symbol)
    log_hits(hits)

    if hits:
        print(f"\n*** {len(hits)} Layer-1-passing signal(s) this pass ***")
        for h in hits:
            print(f"  {h['symbol']:6s} {h['direction']:4s} [{h['config']}/{h['interval']}] "
                  f"entry={h['entry_price']:.2f} mover={h['mover_pct']:+.2f}% ts={h['timestamp']}")
        print(f"\nLogged to {LOG_PATH}")
    else:
        print("\nNo Layer-1-passing signals this pass.")

    print("\nDRY RUN / SIGNAL-ONLY -- no order-placement tool was called or is reachable from this script.")
