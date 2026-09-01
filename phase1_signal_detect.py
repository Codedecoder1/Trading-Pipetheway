"""
Phase 1 (Stage C) -- run the SMC confluence detector, walk-forward style,
against every (symbol, date) mover event in the narrowed 4-week scope
(2026-07-27 through 2026-08-24, 61-symbol universe minus the 8 chronic
movers), using the consolidated 5-minute intraday bars in
narrowed_5min_bars.json. Each (symbol, date) is walked forward
independently -- the consolidation/POC window never spans across days,
matching how the live bot would scan a fresh session each morning.

For each bar step within a day, mover_pct is recomputed vs. that day's
prev_close (same convention as new_movers_walkforward.py) so a signal is
only counted once the intraday move has actually crossed the >=3.0%
production movers threshold -- consistent with the daily-level 3% filter
already applied to build mover_events_narrowed.json, but checked bar-by-bar
so entries are timestamped at the point the signal it would have fired
live, not the eventual end-of-day close.

DRY RUN / SIGNAL-ONLY: this script only detects raw confluence signals.
It does not touch contract_filters.py's Layer 1/2 gate and it never calls
any order-placement tool.
"""
import pandas as pd, json, sys
sys.path.insert(0, '/home/claude/smc_bot')
from smc_confluence import detect_confluence_signal

with open('/home/claude/smc_bot/diag/backtest/narrowed_5min_bars.json') as f:
    bars_by_symbol_date = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/mover_events_narrowed.json') as f:
    events = json.load(f)

MOVER_THRESH = 3.0
configs = [("STRICT", 0.015), ("LOOSE", 0.006)]
interval_specs = [("5min", "5min", 36), ("10min", "10min", 18), ("30min", "30min", 6)]

all_hits = []
skipped_no_data = []
skipped_too_short = []

for e in events:
    sym, date, prev_close = e["symbol"], e["date"], e["prev_close"]
    bars = bars_by_symbol_date.get(sym, {}).get(date)
    if not bars:
        skipped_no_data.append((sym, date))
        continue

    df5 = pd.DataFrame(bars)
    df5 = df5.rename(columns={"open_price": "open", "close_price": "close", "high_price": "high", "low_price": "low"})
    for col in ["open", "close", "high", "low"]:
        df5[col] = df5[col].astype(float)
    df5["volume"] = df5["volume"].astype(float)
    df5["begins_at"] = pd.to_datetime(df5["begins_at"])
    df5 = df5.set_index("begins_at").sort_index()

    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    frames = {
        "5min": df5.reset_index(),
        "10min": df5.resample("10min").agg(agg).dropna().reset_index(),
        "30min": df5.resample("30min").agg(agg).dropna().reset_index(),
    }

    any_frame_long_enough = False
    for label, key, cbars in interval_specs:
        df = frames[key]
        need = cbars + 2
        if len(df) < need:
            continue
        any_frame_long_enough = True
        seen_signals = set()
        for i in range(need, len(df) + 1):
            sub = df.iloc[:i]
            last_close = sub.iloc[-1]["close"]
            mover_pct = (last_close - prev_close) / prev_close * 100
            if abs(mover_pct) < MOVER_THRESH:
                continue
            for cfg_label, thresh in configs:
                sig, poc, pat = detect_confluence_signal(sub, consolidation_bars=cbars, threshold_pct=thresh)
                if sig in ("BULLISH_CONFLUENCE", "BEARISH_CONFLUENCE"):
                    ts = sub.iloc[-1]["begins_at"]
                    key_sig = (sym, date, label, cfg_label, str(ts), sig)
                    if key_sig not in seen_signals:
                        seen_signals.add(key_sig)
                        all_hits.append({
                            "symbol": sym, "date": date, "interval": label, "config": cfg_label,
                            "signal": sig, "timestamp": str(ts), "poc": poc, "pattern": pat,
                            "entry_price": float(last_close), "mover_pct": round(mover_pct, 2),
                            "direction": "call" if sig == "BULLISH_CONFLUENCE" else "put",
                        })
    if not any_frame_long_enough:
        skipped_too_short.append((sym, date, len(df5)))

print(f"Events processed: {len(events)}")
print(f"Skipped (no intraday data): {len(skipped_no_data)}  {skipped_no_data}")
print(f"Skipped (too short for any interval): {len(skipped_too_short)}  {skipped_too_short}")
print(f"Total raw confluence signal hits: {len(all_hits)}")

with open('/home/claude/smc_bot/diag/backtest/phase1_raw_signals.json', 'w') as f:
    json.dump(all_hits, f, indent=2)

# quick breakdown
from collections import Counter
by_symbol = Counter(h["symbol"] for h in all_hits)
by_config = Counter(h["config"] for h in all_hits)
by_interval = Counter(h["interval"] for h in all_hits)
by_direction = Counter(h["direction"] for h in all_hits)
print("\nBy symbol (top 15):", by_symbol.most_common(15))
print("By config:", dict(by_config))
print("By interval:", dict(by_interval))
print("By direction:", dict(by_direction))
