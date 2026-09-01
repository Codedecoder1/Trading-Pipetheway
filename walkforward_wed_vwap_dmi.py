"""
Walk-forward backtest harness for the VWAP-200/DMI/ADX Wednesday-only
strategy (2026-08-30), mirroring walkforward_week.py's approach for the
SMC bot: the live Wednesday trigger fires every 30 minutes, 13:30-19:30
UTC (7 cycles), and each firing only sees hourly bars available as of
that moment. A single end-of-day evaluate() call (vwap_dmi_screener.py's
normal invocation) only checks the LAST bar in the full history, which
is not equivalent to what each of the day's live firings would have seen.

This reuses the real indicator functions (rolling_vwap, adx_dmi, atr) and
the real cross/DI/ADX signal logic from vwap_dmi_screener.py, but recomputes
them against bars truncated to <= each simulated cycle timestamp, then
checks only the newest two rows for a qualifying cross -- same as the
live evaluate() does against its own full-history dataframe.

Caveat: hourly bars are coarser than the 30-min trigger cadence, so
multiple cycles in the same hour will see an identical truncated
dataframe (no new bar has completed yet) until the next hourly bar
appears. This is a faithful representation of what the live bot would
actually see querying hourly data every 30 minutes.

Usage: python3 walkforward_wed_vwap_dmi.py dryrun_hourly_wed.json
"""
import json, sys, os
from datetime import datetime
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vwap_dmi_indicators import rolling_vwap, adx_dmi, atr
from vwap_dmi_screener import WATCHLIST, VWAP_WINDOW, DMI_ADX_LENGTH, ADX_MIN, MIN_BARS_REQUIRED

bars_path = sys.argv[1]
with open(bars_path) as f:
    full_bars_by_symbol = json.load(f)

date_str = "2026-08-26"
cycle_times = [f"{date_str}T{h:02d}:30:00Z" for h in range(13, 20)]  # 13:30 .. 19:30 UTC

print(f"=== WALK-FORWARD WED VWAP/DMI ({date_str}) -- {len(cycle_times)} simulated cycles, "
      f"watchlist {len(WATCHLIST)} symbols, {len(full_bars_by_symbol)} with data ===")

all_signals_this_day = []
first_actionable = None
pending_from_ts = None

for cyc in cycle_times:
    for sym in WATCHLIST:
        bars = full_bars_by_symbol.get(sym, [])
        keep = [b for b in bars if b["begins_at"] <= cyc]
        if len(keep) < MIN_BARS_REQUIRED:
            continue
        df = pd.DataFrame(keep)
        df = df.rename(columns={"open_price": "open", "close_price": "close",
                                 "high_price": "high", "low_price": "low"})
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["begins_at"] = pd.to_datetime(df["begins_at"])
        df = df.drop_duplicates(subset="begins_at").sort_values("begins_at").reset_index(drop=True)

        df["vwap_200"] = rolling_vwap(df, window=VWAP_WINDOW, min_periods=20)
        dmi = adx_dmi(df, length=DMI_ADX_LENGTH)
        df["adx"] = dmi["adx"]
        df["plus_di"] = dmi["plus_di"]
        df["minus_di"] = dmi["minus_di"]
        df["atr"] = atr(df, length=DMI_ADX_LENGTH)

        if len(df) < 2:
            continue
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        if pd.isna(curr["vwap_200"]) or pd.isna(prev["vwap_200"]) or pd.isna(curr["adx"]):
            continue

        close_price = float(curr["close"])
        adx_val = float(curr["adx"])
        plus_di = float(curr["plus_di"])
        minus_di = float(curr["minus_di"])
        atr_val = float(curr["atr"])

        bullish_cross = (prev["close"] <= prev["vwap_200"]) and (curr["close"] > curr["vwap_200"])
        bearish_cross = (prev["close"] >= prev["vwap_200"]) and (curr["close"] < curr["vwap_200"])

        signal_type = None
        if bullish_cross and plus_di > minus_di and adx_val > ADX_MIN:
            signal_type = "BULLISH_CALL"
            direction = "call"
        elif bearish_cross and minus_di > plus_di and adx_val > ADX_MIN:
            signal_type = "BEARISH_PUT"
            direction = "put"
        else:
            continue

        ts = curr["begins_at"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S+00:00")

        key = (sym, direction, ts_str)
        if any(s["symbol"] == sym and s["direction"] == direction and s["timestamp"] == ts_str
               for s in all_signals_this_day):
            continue

        hit = {
            "cycle": cyc, "symbol": sym, "direction": direction, "signal": signal_type,
            "timestamp": ts_str, "entry_price": close_price, "adx_14": round(adx_val, 2),
            "plus_di_14": round(plus_di, 2), "minus_di_14": round(minus_di, 2),
            "atr_14": round(atr_val, 2),
        }
        all_signals_this_day.append(hit)
        print(f"  [{cyc}] NEW signal: {sym:6s} {direction:4s} [{signal_type}] entry={close_price:.2f} "
              f"ADX={adx_val:.1f} +DI={plus_di:.1f} -DI={minus_di:.1f} signal_ts={ts_str}")
        if first_actionable is None and pending_from_ts is None:
            first_actionable = hit
            pending_from_ts = cyc

if not all_signals_this_day:
    print("  No qualifying VWAP/DMI signals at any cycle this day.")
else:
    print(f"\n  {len(all_signals_this_day)} distinct signal(s) detected across the day.")
    if first_actionable:
        print(f"  FIRST actionable signal (what the live bot would have proposed): "
              f"{first_actionable['symbol']} {first_actionable['direction']} "
              f"entry={first_actionable['entry_price']:.2f} signal_ts={first_actionable['timestamp']} "
              f"(cycle {first_actionable['cycle']})")

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "walkforward_wed.json")
json.dump({"date": date_str, "signals": all_signals_this_day, "first_actionable": first_actionable},
          open(out_path, "w"), indent=2)
print(f"\n  Saved to {out_path}")
