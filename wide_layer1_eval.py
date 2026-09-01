"""
Wide-window Layer 1 evaluation -- the direct wide-window analogue of
phase1_layer1_eval_v5.py, run against wide_raw_signals.json (227 hits from
Stage C over the 14-week window) using wide_5min_bars.json for
volume-impulse/VWAP and the existing daily_bars_with_indicators.json for
advisory ATR14 (that file already spans 2026-05-01 through 2026-08-24 across
all 61 universe symbols, so it covers this wider window without needing to
be rebuilt).

Layer 1 = check_volume_impulse AND check_vwap_alignment AND
check_session_time (REVISION 8, contract_filters.py) -- identical gate to
v5, just run at the wider n.

DRY RUN / SIGNAL-ONLY: evaluation only. No order-placement tool is called.
"""
import json, sys
import pandas as pd
sys.path.insert(0, '/home/claude/smc_bot')
from contract_filters import check_volume_impulse, check_vwap_alignment, check_atr_pct, check_session_time, VERSION_LABEL

with open('/home/claude/smc_bot/diag/backtest/wide_raw_signals.json') as f:
    signals = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/wide_5min_bars.json') as f:
    bars_by_symbol_date = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/daily_bars_with_indicators.json') as f:
    daily = json.load(f)

prior_day_indicators = {}
for sym, rows in daily.items():
    rows_sorted = sorted(rows, key=lambda r: r["begins_at"])
    prior_day_indicators[sym] = {}
    prev = None
    for r in rows_sorted:
        date = r["begins_at"][:10]
        if prev is not None:
            prior_day_indicators[sym][date] = {"atr14": prev["atr14"], "avg_vol_30d": prev["avg_vol_30d"]}
        prev = r

SESSION_OPEN_MIN = 13 * 60 + 30
INTERVAL_RESAMPLE = {"5min": "5min", "10min": "10min", "30min": "30min"}

results = []
skipped = []

for s in signals:
    sym, date, interval_label = s["symbol"], s["date"], s["interval"]
    bars = bars_by_symbol_date.get(sym, {}).get(date)
    ind = prior_day_indicators.get(sym, {}).get(date)
    if not bars:
        skipped.append({**s, "skip_reason": "missing intraday bars"})
        continue

    df5 = pd.DataFrame(bars)
    df5["begins_at"] = pd.to_datetime(df5["begins_at"])
    df5 = df5.sort_values("begins_at").reset_index(drop=True)
    for col in ["open_price", "close_price", "high_price", "low_price"]:
        df5[col] = df5[col].astype(float)
    df5["volume"] = df5["volume"].astype(float)

    ts = pd.to_datetime(s["timestamp"])

    up_to_5 = df5[df5["begins_at"] <= ts]
    typical = (up_to_5["high_price"] + up_to_5["low_price"] + up_to_5["close_price"]) / 3.0
    vwap_at_entry = (float((typical * up_to_5["volume"]).sum() / up_to_5["volume"].sum())
                      if up_to_5["volume"].sum() > 0 else float(up_to_5["close_price"].iloc[-1]))

    df5i = df5.set_index("begins_at")
    if interval_label == "5min":
        df_interval = df5.copy()
    else:
        agg = {"open_price": "first", "high_price": "max", "low_price": "min",
               "close_price": "last", "volume": "sum"}
        df_interval = df5i.resample(INTERVAL_RESAMPLE[interval_label]).agg(agg).dropna().reset_index()

    up_to_interval = df_interval[df_interval["begins_at"] <= ts]
    if up_to_interval.empty:
        skipped.append({**s, "skip_reason": "no interval bars at/before signal timestamp"})
        continue
    signal_bar_volume = float(up_to_interval["volume"].iloc[-1])
    recent_bar_volumes = [float(v) for v in up_to_interval["volume"].iloc[:-1].tolist()]

    entry_price = s["entry_price"]
    direction = s["direction"]

    if ind and ind["atr14"] == ind["atr14"]:
        atr_ok, atr_note = check_atr_pct(ind["atr14"], entry_price)
    else:
        atr_ok, atr_note = None, "no prior-day ATR14 available"

    vi_ok, vi_note = check_volume_impulse(signal_bar_volume, recent_bar_volumes)
    vwap_ok, vwap_note = check_vwap_alignment(entry_price, vwap_at_entry, direction)
    session_ok, session_note = check_session_time(s["timestamp"])
    layer1_passed = vi_ok and vwap_ok and session_ok

    results.append({
        **s,
        "vwap_at_entry": round(vwap_at_entry, 4),
        "signal_bar_volume": signal_bar_volume, "trailing_bar_count": len(recent_bar_volumes),
        "atr14": ind["atr14"] if ind else None,
        "layer1_passed": layer1_passed,
        "checks": {
            "volume_impulse": {"ok": vi_ok, "note": vi_note},
            "vwap": {"ok": vwap_ok, "note": vwap_note},
            "session_time": {"ok": session_ok, "note": session_note},
        },
        "advisory": {
            "atr_pct": {"ok": atr_ok, "note": atr_note},
        },
    })

n_pass = sum(1 for r in results if r["layer1_passed"])
print(f'=== "{VERSION_LABEL}" REVISION 8 -- WIDE-WINDOW Layer 1 Signal Log ===')
print(f"Raw signals: {len(signals)}")
print(f"Evaluated: {len(results)}  (skipped: {len(skipped)})")
print(f"Layer 1 PASS: {n_pass} / {len(results)}")

with open('/home/claude/smc_bot/diag/backtest/wide_layer1_signal_log.json', 'w') as f:
    json.dump({"results": results, "skipped": skipped}, f, indent=2)

print("\n--- PASSING signals ---")
for r in results:
    if r["layer1_passed"]:
        print(f"  {r['symbol']:6s} {r['date']} {r['direction']:4s} [{r['config']}/{r['interval']}] "
              f"entry={r['entry_price']:.2f} ts={r['timestamp']}")

print("\n--- Failure breakdown ---")
from collections import Counter
fail_reasons = Counter()
for r in results:
    if not r["layer1_passed"]:
        failed_checks = tuple(k for k, v in r["checks"].items() if not v["ok"])
        fail_reasons[failed_checks] += 1
for reason, n in fail_reasons.most_common():
    print(f"  failed={reason}: {n}")

if skipped:
    print("\n--- Skipped ---")
    for r in skipped:
        print(f"  {r['symbol']:6s} {r['date']}  reason={r['skip_reason']}")
