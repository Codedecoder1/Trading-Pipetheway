"""
Shared append-only "moves log" for the live notify-and-confirm pipeline.

WHY THIS EXISTS: pending_live_orders.json only ever holds the CURRENT
state of orders (awaiting_confirmation / confirmed / expired / rejected
never even gets a row there) -- it's a snapshot, not a history. Once an
order is confirmed and a fresh one prepared, or once 15 minutes passes
and something expires, the older row's context is easy to lose track of
across sessions. trade_log.jsonl is the durable, append-only record of
every decision point in the pipeline: a rejected proposal, a prepared
proposal, an executed order, a stop-loss placed, a position closed. It is
never rewritten, only appended to -- so it survives across every future
session and every scheduled firing, and answers "what has this bot
actually done, ever" without having to reconstruct it from scratch.

Each line is one JSON object:
  {
    "logged_at_utc": ISO timestamp,
    "event": one of the EVENT_TYPES below,
    ...event-specific fields...
  }

Human-readable rendering: run render_trade_log.py after appending to
regenerate TRADE_LOG.md from the full history in this file.
"""
import json, os
from datetime import datetime, timezone

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
LOG_PATH = os.path.join(BACKTEST_DIR, 'trade_log.jsonl')

EVENT_TYPES = {
    "log_initialized",       # one-time marker, records the live parameters in effect when logging began
    "proposal_prepared",     # live_prepare_order.py: all risk checks passed, order written to pending_live_orders.json
    "proposal_rejected",     # live_prepare_order.py: a risk check failed, nothing was written
    "signal_only_not_executed",  # live_prepare_order.py, REVISION 10 (2026-08-27): signal passed
                              # Layer 1 (including session_time) but fired after EXECUTION_CUTOFF
                              # (19:30:00 UTC) -- logged for visibility, no risk checks run, no
                              # order proposed. Distinct from proposal_rejected: nothing about the
                              # signal or contract was wrong, there just wasn't session time left
                              # to manage the trade.
    "order_expired",         # live_expire_stale_orders.py: an awaiting_confirmation order aged out (>15 min)
    "order_confirmed_executed",  # live_execute_order.py: user confirmed, place_option_order was actually called
    "position_closed",       # live_log_position_closed.py: a position was closed (stop hit or manual), realized P&L known
}


def append_event(event, **fields):
    """Append one event to trade_log.jsonl. `event` must be one of
    EVENT_TYPES. Never raises on a logging failure other than a bad event
    name -- a logging bug should never be allowed to break the live
    pipeline it's observing, so callers can treat this as best-effort."""
    if event not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event!r}, must be one of {sorted(EVENT_TYPES)}")
    record = {"logged_at_utc": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(record) + "\n")
    except Exception as ex:
        # Best-effort: print so it's visible in the calling session's output,
        # but never raise -- a logging failure must never block or crash the
        # live risk-check / order pipeline itself.
        print(f"WARNING: trade_log append failed ({ex}) -- event was: {record}")
    return record


def read_all():
    """Returns the full event history as a list of dicts, oldest first."""
    if not os.path.exists(LOG_PATH):
        return []
    events = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events
