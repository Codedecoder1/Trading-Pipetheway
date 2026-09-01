"""
Phase 1 (Stage D, v2) -- re-evaluate every raw confluence signal from
phase1_raw_signals.json against the REVISION 5 Layer 1 gate
(check_volume_confirmation's OR-gate: time-of-day RVOL >= 0.75x OR
signal-bar volume >= 2.0x the trailing 20-bar volume MA, at whatever
interval -- 5/10/30min -- the signal fired on; ATR14 daily %; VWAP
alignment).

Same no-lookahead discipline as v1: ATR14/avg_volume_30d come from the
PRIOR completed trading day's close. volume_so_far/vwap_at_entry are
still the true cumulative 5-min-bar volume/VWAP from session open through
the signal's timestamp (used for the RVOL clause). NEW in v2:
signal_bar_volume and recent_bar_volumes are pulled from the resampled
bars AT THE SIGNAL'S OWN INTERVAL (5/10/30min), matching what
check_volume_confirmation's spike clause needs -- both computed purely
from the intraday feed, so there's no cross-feed accounting mismatch on
that side of the OR-gate.

DRY RUN / SIGNAL-ONLY: evaluation only. No order-placement tool is
called, regardless of the result.
"""
import json, sys
import pandas as pd
sys.path.insert(0, '/home/claude/smc_bot')
from contract_filters import check_atr_pct, check_vwap_alignment, check_volume_confirmation, VERSION_LABEL

with open('/home/claude/smc_bot/diag/backtest/phase1_raw_signals.json') as f:
    signals = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/narrowed_5min_bars.json') as f:
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

def minutes_since_open(ts):
    return ts.hour * 60 + ts.minute - SESSION_OPEN_MIN

results = []
skipped = []

for s in signals:
    sym, date, interval_label = s["symbol"], s["date"], s["interval"]
    bars = bars_by_symbol_date.get(sym, {}).get(date)
    ind = prior_day_indicators.get(sym, {}).get(date)
    if not bars or not ind or ind["atr14"] != ind["atr14"] or ind["avg_vol_30d"] != ind["avg_vol_30d"]:
        skipped.append({**s, "skip_reason": "missing prior-day ATR14/avg_vol_30d"})
        continue

    df5 = pd.DataFrame(bars)
    df5["begins_at"] = pd.to_datetime(df5["begins_at"])
    df5 = df5.sort_values("begins_at").reset_index(drop=True)
    for col in ["open_price", "close_price", "high_price", "low_price"]:
        df5[col] = df5[col].astype(float)
    df5["volume"] = df5["volume"].astype(float)

    ts = pd.to_datetime(s["timestamp"])

    # --- RVOL-clause inputs: cumulative 5-min volume/VWAP through ts ---
    up_to_5 = df5[df5["begins_at"] <= ts]
    volume_so_far = float(up_to_5["volume"].sum())
    typical = (up_to_5["high_price"] + up_to_5["low_price"] + up_to_5["close_price"]) / 3.0
    vwap_at_entry = (float((typical * up_to_5["volume"]).sum() / up_to_5["volume"].sum())
                      if up_to_5["volume"].sum() > 0 else float(up_to_5["close_price"].iloc[-1]))
    elapsed_minutes = minutes_since_open(ts) + 5

    # --- spike-clause inputs: signal-bar volume + trailing 20 bars AT THE SIGNAL'S OWN INTERVAL ---
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
    recent_bar_volumes = [float(v) for v in up_to_interval["volume"].iloc[:-1].tolist()]  # strictly before signal bar

    atr = ind["atr14"]
    avg_vol_30d = ind["avg_vol_30d"]
    entry_price = s["entry_price"]
    direction = s["direction"]

    vc_ok, vc_note = check_volume_confirmation(volume_so_far, avg_vol_30d, elapsed_minutes,
                                                signal_bar_volume, recent_bar_volumes)
    atr_ok, atr_note = check_atr_pct(atr, entry_price)
    vwap_ok, vwap_note = check_vwap_alignment(entry_price, vwap_at_entry, direction)
    layer1_passed = vc_ok and atr_ok and vwap_ok

    results.append({
        **s,
        "volume_so_far": volume_so_far, "avg_volume_30d": avg_vol_30d,
        "elapsed_minutes": elapsed_minutes, "atr14": atr, "vwap_at_entry": round(vwap_at_entry, 4),
        "signal_bar_volume": signal_bar_volume, "trailing_bar_count": len(recent_bar_volumes),
        "layer1_passed": layer1_passed,
        "checks": {
            "volume_confirmation": {"ok": vc_ok, "note": vc_note},
            "atr_pct": {"ok": atr_ok, "note": atr_note},
            "vwap": {"ok": vwap_ok, "note": vwap_note},
        },
    })

n_pass = sum(1 for r in results if r["layer1_passed"])
print(f'=== "{VERSION_LABEL}" REVISION 5 -- Phase 1 Layer 1 Signal Log (v2, OR-gate) ===')
print(f"Raw signals: {len(signals)}")
print(f"Evaluated: {len(results)}  (skipped: {len(skipped)})")
print(f"Layer 1 PASS: {n_pass} / {len(results)}")

with open('/home/claude/smc_bot/diag/backtest/phase1_layer1_signal_log_v2.json', 'w') as f:
    json.dump({"results": results, "skipped": skipped}, f, indent=2)

print("\n--- PASSING signals ---")
for r in results:
    if r["layer1_passed"]:
        print(f"  {r['symbol']:6s} {r['date']} {r['direction']:4s} [{r['config']}/{r['interval']}] "
              f"entry={r['entry_price']:.2f} ts={r['timestamp']}")
        print(f"      {r['checks']['volume_confirmation']['note']}")

print("\n--- Failure breakdown ---")
from collections import Counter
fail_reasons = Counter()
for r in results:
    if not r["layer1_passed"]:
        failed_checks = tuple(k for k, v in r["checks"].items() if not v["ok"])
        fail_reasons[failed_checks] += 1
for reason, n in fail_reasons.most_common():
    print(f"  failed={reason}: {n}")
