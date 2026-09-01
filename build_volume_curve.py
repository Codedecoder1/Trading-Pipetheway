"""
Build an empirical intraday cumulative-volume-fraction curve from the
narrowed 4-week mover-day dataset (45 symbols x 123 symbol-days, 9,594
5-min bars). This replaces the linear "elapsed_minutes/390" assumption
in check_rvol_relative, which assumes volume is spread evenly across the
session -- real intraday volume is U-shaped (heavy at the open and
close, light midday), so the linear assumption was making RVOL fail
almost everything even on genuinely elevated-volume days.

Method: for each symbol-day, normalize each 5-min bar's volume by that
day's total volume (giving a fraction-of-day-volume curve), align by
slot index (0..77, one per 5-min bar from 13:30 to 19:55 UTC), average
across all symbol-days, then cumsum to get the expected fraction of a
full day's volume that should have printed by the close of each slot.
"""
import json
import pandas as pd
import numpy as np

with open('/home/claude/smc_bot/diag/backtest/narrowed_5min_bars.json') as f:
    bars_by_symbol_date = json.load(f)

SESSION_OPEN_MIN = 13 * 60 + 30
N_SLOTS = 78  # 390 min / 5

slot_fracs = []  # list of arrays, one per symbol-day, len 78 (or shorter if partial)
skipped_partial = 0

for sym, dates in bars_by_symbol_date.items():
    for date, bars in dates.items():
        df = pd.DataFrame(bars)
        df["begins_at"] = pd.to_datetime(df["begins_at"])
        df["volume"] = df["volume"].astype(float)
        df = df.sort_values("begins_at").reset_index(drop=True)
        if len(df) != N_SLOTS:
            skipped_partial += 1
            continue
        day_total = df["volume"].sum()
        if day_total <= 0:
            continue
        frac = (df["volume"] / day_total).values
        slot_fracs.append(frac)

print(f"symbol-days used: {len(slot_fracs)}  (skipped {skipped_partial} with != {N_SLOTS} bars)")

arr = np.array(slot_fracs)  # shape (n_days, 78)
avg_slot_frac = arr.mean(axis=0)
cum_frac = np.cumsum(avg_slot_frac)
cum_frac = np.clip(cum_frac, 1e-6, 1.0)  # avoid div-by-zero, cap at 1.0

# sanity: print a handful of checkpoints
checkpoints = [0, 5, 12, 24, 36, 48, 60, 71, 77]
print("\nslot -> minutes_elapsed -> empirical cum_frac -> linear elapsed_frac")
for i in checkpoints:
    minutes_elapsed = (i + 1) * 5
    linear = minutes_elapsed / 390.0
    print(f"  slot {i:2d}  {minutes_elapsed:3d}min   empirical={cum_frac[i]:.4f}   linear={linear:.4f}")

out = {
    "n_symbol_days": len(slot_fracs),
    "slot_minutes_elapsed": [(i + 1) * 5 for i in range(N_SLOTS)],
    "cum_frac": cum_frac.tolist(),
}
with open('/home/claude/smc_bot/diag/backtest/empirical_volume_curve.json', 'w') as f:
    json.dump(out, f, indent=2)
print("\nSaved empirical_volume_curve.json")
