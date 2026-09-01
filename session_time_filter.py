"""
Late-Session No-Trade Zone (per user's explicit directive after the Phase 2
Synthetic Underlying Replay run): reject any signal firing after 19:30Z
(3:30pm EST/EDT, 30 minutes before the 20:00Z regular-session close).

Rationale, directly from this backtest's own results: the 3 setups whose
signal timestamp fell AFTER 19:30Z (AMZN 8/3 @ 19:55Z, NVDA 8/12 @ 19:50Z,
SHW 7/27 @ 19:50Z) left only 5-10 minutes of the session to replay --
several of their legs never got the chance to trigger the phase-1 trailing
stop, hard stop, OR TP1 before the exit engine ran out of bars and had to
mark them STILL_OPEN at whatever the last synthetic print happened to be.
That's not a signal-quality problem (Layer 1 passed these fine) -- it's a
structural risk: entering an intraday-managed options position with too
little runway left in the session to actually manage it, which in live
trading means either an unhedged short-dated option held overnight or a
forced market-on-close exit neither the strategy nor this backtest
accounts for.

Policy: reject entries with timestamp > 19:30:00Z on their own session day
(inclusive of exactly 19:30:00Z, which stays eligible -- it's the boundary,
not past it). This is a scheduling/session-risk gate, kept separate from
contract_filters.py's Layer 1 (which screens signal QUALITY: volume impulse
+ VWAP alignment) since this is about whether there's enough clock left to
run the trade plan at all, not whether the signal itself is good.

DRY RUN / SIGNAL-ONLY: this only reclassifies which historical signals
would have been ELIGIBLE to trade under this policy. No order-placement
tool is called.
"""
import json
from datetime import time

CUTOFF = time(19, 30, 0)  # 19:30:00Z: reject strictly AFTER this, boundary itself stays eligible


def passes_late_session_filter(timestamp_str, cutoff=CUTOFF):
    """timestamp_str: 'YYYY-MM-DD HH:MM:SS+00:00' or ISO 'YYYY-MM-DDTHH:MM:SSZ'
    (both formats appear across this repo's signal logs). Returns
    (passes: bool, note: str)."""
    # normalize to just the HH:MM:SS portion, both formats put it at the same offset
    hms = timestamp_str[11:19]
    h, m, sec = (int(x) for x in hms.split(":"))
    t = time(h, m, sec)
    if t > cutoff:
        return False, f"signal fires at {hms}Z, after the 19:30:00Z late-session cutoff " \
                       f"({(t.hour*60+t.minute) - (cutoff.hour*60+cutoff.minute)} min past cutoff, " \
                       f"only {20*60 - (t.hour*60+t.minute)} min left to session close)"
    return True, f"signal fires at {hms}Z, within the tradeable window (cutoff 19:30:00Z)"


if __name__ == "__main__":
    with open('/home/claude/smc_bot/diag/backtest/phase1_layer1_signal_log_v4.json') as f:
        d = json.load(f)
    passing = [r for r in d["results"] if r["layer1_passed"]]

    kept, rejected = [], []
    for r in passing:
        ok, note = passes_late_session_filter(r["timestamp"])
        (kept if ok else rejected).append({**r, "session_filter_note": note})

    print(f"=== Late-Session No-Trade Zone (cutoff 19:30:00Z) ===")
    print(f"Layer-1-passing signals in: {len(passing)}")
    print(f"Eligible (kept):            {len(kept)}")
    print(f"Rejected (after cutoff):    {len(rejected)}\n")

    print("--- Kept ---")
    for r in kept:
        print(f"  {r['symbol']:6s} {r['date']} [{r['config']}/{r['interval']}]  {r['session_filter_note']}")

    print("\n--- Rejected ---")
    for r in rejected:
        print(f"  {r['symbol']:6s} {r['date']} [{r['config']}/{r['interval']}]  {r['session_filter_note']}")

    with open('/home/claude/smc_bot/diag/backtest/phase1_layer1_signal_log_v4_session_filtered.json', 'w') as f:
        json.dump({"kept": kept, "rejected": rejected, "cutoff": "19:30:00Z"}, f, indent=2, default=str)
