"""
Phase 1 (Stage D) -- evaluate every raw confluence signal from
phase1_raw_signals.json against the LOCKED Layer 1 of contract_filters.py
(RVOL_MIN=1.0 time-of-day-relative, ATR_PCT_MIN=2.0 using DAILY ATR(14),
VWAP alignment). This produces the "clean Layer 1 Pass/Fail Signal Log"
that is Phase 1's explicit deliverable.

No-lookahead discipline: ATR14 and avg_volume_30d are pulled from the
PRIOR completed trading day's close (shifted by one row per symbol in
daily_bars_with_indicators.json), matching what would actually be known
at the start of the signal's trading day live -- NOT the same-day
rolling value (which would leak same-day range/volume into the gate).

volume_so_far is the true cumulative 5-minute-bar volume from session
open (13:30 UTC) through the signal's timestamp, computed directly from
narrowed_5min_bars.json. vwap_at_entry is the cumulative volume-weighted
average price from session open through that same timestamp (typical
price = (h+l+c)/3 per bar, matching the convention used earlier this
session for the "best one yet" re-run).

DRY RUN / SIGNAL-ONLY: evaluation only. No order-placement tool is
called, regardless of the result.
"""
import json, sys
import pandas as pd
sys.path.insert(0, '/home/claude/smc_bot')
from contract_filters import check_rvol_relative, check_atr_pct, check_vwap_alignment, VERSION_LABEL

with open('/home/claude/smc_bot/diag/backtest/phase1_raw_signals.json') as f:
    signals = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/narrowed_5min_bars.json') as f:
    bars_by_symbol_date = json.load(f)

with open('/home/claude/smc_bot/diag/backtest/daily_bars_with_indicators.json') as f:
    daily = json.load(f)

# Build prior-day-close lookup: symbol -> date -> {atr14, avg_vol_30d} using
# the PREVIOUS row's values (no lookahead).
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

SESSION_OPEN_MIN = 13 * 60 + 30  # 13:30 UTC in minutes-of-day

def minutes_since_open(ts):
    return ts.hour * 60 + ts.minute - SESSION_OPEN_MIN

results = []
skipped = []

for s in signals:
    sym, date = s["symbol"], s["date"]
    bars = bars_by_symbol_date.get(sym, {}).get(date)
    ind = prior_day_indicators.get(sym, {}).get(date)
    if not bars or not ind or ind["atr14"] != ind["atr14"] or ind["avg_vol_30d"] != ind["avg_vol_30d"]:
        # NaN check via self-inequality (NaN != NaN)
        skipped.append({**s, "skip_reason": "missing prior-day ATR14/avg_vol_30d (insufficient history at start of window)"})
        continue

    df = pd.DataFrame(bars)
    df["begins_at"] = pd.to_datetime(df["begins_at"])
    df = df.sort_values("begins_at")
    for col in ["open_price", "close_price", "high_price", "low_price"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)

    ts = pd.to_datetime(s["timestamp"])
    up_to = df[df["begins_at"] <= ts]
    if up_to.empty:
        skipped.append({**s, "skip_reason": "no bars at/before signal timestamp"})
        continue

    volume_so_far = float(up_to["volume"].sum())
    typical = (up_to["high_price"] + up_to["low_price"] + up_to["close_price"]) / 3.0
    vwap_at_entry = float((typical * up_to["volume"]).sum() / up_to["volume"].sum()) if up_to["volume"].sum() > 0 else float(up_to["close_price"].iloc[-1])
    elapsed_minutes = minutes_since_open(ts) + 5  # +5: bar covers [ts, ts+5min), so 5 min have elapsed by bar close

    atr = ind["atr14"]
    avg_vol_30d = ind["avg_vol_30d"]
    entry_price = s["entry_price"]
    direction = s["direction"]

    rvol_ok, rvol_note = check_rvol_relative(volume_so_far, avg_vol_30d, elapsed_minutes)
    atr_ok, atr_note = check_atr_pct(atr, entry_price)
    vwap_ok, vwap_note = check_vwap_alignment(entry_price, vwap_at_entry, direction)
    layer1_passed = rvol_ok and atr_ok and vwap_ok

    results.append({
        **s,
        "volume_so_far": volume_so_far, "avg_volume_30d": avg_vol_30d,
        "elapsed_minutes": elapsed_minutes, "atr14": atr, "vwap_at_entry": round(vwap_at_entry, 4),
        "layer1_passed": layer1_passed,
        "checks": {
            "rvol_relative": {"ok": rvol_ok, "note": rvol_note},
            "atr_pct": {"ok": atr_ok, "note": atr_note},
            "vwap": {"ok": vwap_ok, "note": vwap_note},
        },
    })

n_pass = sum(1 for r in results if r["layer1_passed"])
print(f'=== "{VERSION_LABEL}" -- Phase 1 Layer 1 Signal Log ===')
print(f"Raw signals: {len(signals)}")
print(f"Evaluated: {len(results)}  (skipped: {len(skipped)} -- insufficient prior-day history)")
print(f"Layer 1 PASS: {n_pass} / {len(results)}")

with open('/home/claude/smc_bot/diag/backtest/phase1_layer1_signal_log.json', 'w') as f:
    json.dump({"results": results, "skipped": skipped}, f, indent=2)

print("\n--- PASSING signals ---")
for r in results:
    if r["layer1_passed"]:
        fails = []
        print(f"  {r['symbol']:6s} {r['date']} {r['direction']:4s} [{r['config']}/{r['interval']}] "
              f"entry={r['entry_price']:.2f} ts={r['timestamp']} "
              f"rvol_ok atr_ok vwap_ok")

print("\n--- Failure breakdown (which check killed each failing signal) ---")
from collections import Counter
fail_reasons = Counter()
for r in results:
    if not r["layer1_passed"]:
        failed_checks = tuple(k for k, v in r["checks"].items() if not v["ok"])
        fail_reasons[failed_checks] += 1
for reason, n in fail_reasons.most_common():
    print(f"  failed={reason}: {n}")

if skipped:
    print("\n--- Skipped (no usable prior-day ATR/volume history) ---")
    for r in skipped:
        print(f"  {r['symbol']:6s} {r['date']}")
