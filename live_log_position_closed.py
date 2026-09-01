"""
Records that an open position was closed -- either the protective
stop_market sell filled on its own, or it was closed manually (e.g. the
user asked to exit early, or the option expired). Run this from an
interactive session once you've confirmed (via get_option_positions /
get_option_orders / get_realized_pnl) that the position is actually
closed and you know the real exit price.

Usage:
  python3 live_log_position_closed.py \
    --order-id <the pending order's own order_id> \
    --exit-reason "stop_hit" | "manual_close" | "expired_worthless" \
    --exit-price <actual exit premium per contract> \
    --realized-pnl <dollars, signed -- negative for a loss> \
    --notes "<optional>"
"""
import argparse, json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from trade_log import append_event

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
PENDING_PATH = os.path.join(BACKTEST_DIR, 'pending_live_orders.json')

p = argparse.ArgumentParser()
p.add_argument('--order-id', required=True)
p.add_argument('--exit-reason', required=True, choices=['stop_hit', 'manual_close', 'expired_worthless'])
p.add_argument('--exit-price', required=True, type=float)
p.add_argument('--realized-pnl', required=True, type=float)
p.add_argument('--notes', default=None)
args = p.parse_args()

match = None
if os.path.exists(PENDING_PATH):
    orders = json.load(open(PENDING_PATH))
    match = next((o for o in orders if o.get('order_id') == args.order_id), None)
    if match is not None:
        match['status'] = 'closed'
        match['closed_at_utc'] = datetime.now(timezone.utc).isoformat()
        match['exit_reason'] = args.exit_reason
        match['exit_price'] = args.exit_price
        match['realized_pnl'] = args.realized_pnl
        if args.notes:
            match['close_notes'] = args.notes
        json.dump(orders, open(PENDING_PATH, 'w'), indent=2)

if match is None:
    print(f"WARNING: order_id={args.order_id!r} not found in {PENDING_PATH} -- "
          f"logging the closure event anyway (pending_live_orders.json entry not updated).")

append_event(
    "position_closed",
    order_id=args.order_id,
    symbol=(match or {}).get('symbol'), direction=(match or {}).get('direction'),
    strike=(match or {}).get('strike'), expiration=(match or {}).get('expiration'),
    entry_fill_price=(match or {}).get('actual_fill_price') or (match or {}).get('limit_price'),
    exit_reason=args.exit_reason, exit_price=args.exit_price,
    realized_pnl=args.realized_pnl, notes=args.notes,
)

print(f"LOGGED: position {args.order_id} closed ({args.exit_reason}), "
      f"exit ${args.exit_price:.2f}, realized P&L ${args.realized_pnl:+.2f}.")
