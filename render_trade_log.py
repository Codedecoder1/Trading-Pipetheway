"""
Renders trade_log.jsonl into a human-readable TRADE_LOG.md -- run this any
time you want an up-to-date document (it's a pure re-render from the
append-only source of truth, safe to run as often as you like).

Usage: python3 render_trade_log.py
"""
import os, sys
from collections import defaultdict
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from trade_log import read_all

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
OUT_PATH = os.path.join(BACKTEST_DIR, 'TRADE_LOG.md')


def fmt_ts(iso_ts):
    """UTC ISO timestamp -> 'YYYY-MM-DD HH:MM UTC'."""
    if not iso_ts:
        return "?"
    return iso_ts.replace("T", " ")[:16] + " UTC"


def describe(ev):
    e = ev.get("event")
    sym = ev.get("symbol", "?")
    direction = (ev.get("direction") or "").upper()
    strike = ev.get("strike")
    exp = ev.get("expiration")
    tag = f"{sym} {direction} ${strike} exp {exp}" if strike is not None else sym

    if e == "log_initialized":
        return f"**Trade log started.** {ev.get('note', '')}"
    if e == "proposal_prepared":
        return (f"**Proposal prepared** -- {tag}. Limit buy @ ${ev.get('limit_price'):.2f} "
                f"(bid ${ev.get('bid_at_prep'):.2f}), planned stop @ ${ev.get('planned_hard_stop_price'):.2f}. "
                f"Signal fired {ev.get('signal_timestamp')}. Order id `{ev.get('order_id')}`.")
    if e == "proposal_rejected":
        failed = ev.get("failed_checks") or {}
        reasons = "; ".join(f"{k}: {v}" for k, v in failed.items())
        return f"**Proposal rejected** -- {tag}. Failed: {reasons or 'unspecified'}."
    if e == "order_expired":
        return (f"**Proposal expired unconfirmed** -- {tag} @ ${ev.get('limit_price')}. "
                f"Sat unconfirmed for {ev.get('age_minutes')} min. Order id `{ev.get('order_id')}`.")
    if e == "order_confirmed_executed":
        return (f"**EXECUTED** -- {tag}. Filled @ ${ev.get('fill_price'):.2f}, protective stop set @ "
                f"${ev.get('planned_hard_stop_price'):.2f}. Robinhood order `{ev.get('robinhood_order_id')}`"
                + (f", stop order `{ev.get('stop_order_id')}`" if ev.get('stop_order_id') else "")
                + (f". {ev.get('notes')}" if ev.get('notes') else ""))
    if e == "position_closed":
        pnl = ev.get("realized_pnl")
        pnl_str = f"${pnl:+.2f}" if pnl is not None else "?"
        return (f"**CLOSED** ({ev.get('exit_reason')}) -- {tag}. Exit @ ${ev.get('exit_price')}, "
                f"realized P&L {pnl_str}." + (f" {ev.get('notes')}" if ev.get('notes') else ""))
    if e == "exit_proposed":
        return (f"**Exit proposed** [{ev.get('rule')}] -- position `{ev.get('position_id')}`. "
                f"{ev.get('reason', '')}")
    if e == "exit_expired":
        return (f"**Exit proposal expired unconfirmed** [{ev.get('rule')}] -- "
                f"position `{ev.get('position_id')}`, sat {ev.get('age_minutes')} min.")
    return f"{e}: {ev}"


def main():
    events = read_all()

    lines = []
    lines.append("# SMC Volume Bot -- Trade Log")
    lines.append("")
    lines.append("Auto-generated from `trade_log.jsonl` by `render_trade_log.py`. "
                  "Every proposal, rejection, execution, and closure the live pipeline "
                  "has ever produced, in order. Re-run the script to refresh this file "
                  "after new activity -- it never needs manual editing.")
    lines.append("")

    if not events:
        lines.append("*No moves logged yet.* The live monitor is scheduled and will log "
                      "here automatically the first time a signal clears every risk gate.")
        lines.append("")
        with open(OUT_PATH, 'w') as f:
            f.write("\n".join(lines))
        print(f"wrote {OUT_PATH} (0 events)")
        return

    # --- summary stats ---
    counts = defaultdict(int)
    executed = []
    closed = []
    for ev in events:
        counts[ev.get("event")] += 1
        if ev.get("event") == "order_confirmed_executed":
            executed.append(ev)
        if ev.get("event") == "position_closed":
            closed.append(ev)

    total_realized = sum(c.get("realized_pnl", 0) or 0 for c in closed)
    open_count = len(executed) - len(closed)

    lines.append(f"**Summary as of {fmt_ts(events[-1]['logged_at_utc'])}:** "
                 f"{counts.get('proposal_prepared', 0)} proposal(s) prepared, "
                 f"{counts.get('proposal_rejected', 0)} rejected on risk checks, "
                 f"{counts.get('order_expired', 0)} expired unconfirmed, "
                 f"{len(executed)} executed, {len(closed)} closed, {open_count} currently open. "
                 f"Realized P&L to date: **${total_realized:+.2f}**.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Activity (newest first)")
    lines.append("")

    for ev in reversed(events):
        lines.append(f"- `{fmt_ts(ev.get('logged_at_utc'))}` -- {describe(ev)}")

    lines.append("")
    with open(OUT_PATH, 'w') as f:
        f.write("\n".join(lines))
    print(f"wrote {OUT_PATH} ({len(events)} events)")


if __name__ == "__main__":
    main()
