"""
Records that a pending proposal was actually confirmed and executed.

This does NOT call place_option_order itself -- that MCP tool can only be
called from the interactive Claude session (never from a scheduled/
unattended one, per the standing non-negotiable rule), so the real flow
is:

  1. User confirms a specific order_id in an interactive session.
  2. That session re-verifies price/spread are still fresh (per the
     pending order's own notification text), then calls
     mcp__RBH__place_option_order (limit buy, 1 contract) itself.
  3. Immediately after, it calls mcp__RBH__place_option_order again for
     the protective stop_market sell, using the pending order's own
     planned_hard_stop_price.
  4. ONLY once both of those calls have actually succeeded does that
     session run this script, passing back the real order IDs/fill info
     Robinhood returned -- this script's only job is to mark the
     pending_live_orders.json entry as executed and append the
     order_confirmed_executed event to trade_log.jsonl. If this script
     is run without step 2/3 having actually happened, the log will
     claim an execution that never occurred -- so never run this before
     the place_option_order calls have both returned success.

Usage (all args required except --stop-order-id, --notes):
  python3 live_log_execution.py \
    --order-id <pending order's own uuid from pending_live_orders.json> \
    --robinhood-order-id <the id place_option_order returned for the buy> \
    --stop-order-id <the id place_option_order returned for the stop_market sell> \
    --fill-price <actual average fill price, if known, else the limit price> \
    --notes "<anything worth recording, optional>"
"""
import argparse, json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from trade_log import append_event

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
PENDING_PATH = os.path.join(BACKTEST_DIR, 'pending_live_orders.json')

p = argparse.ArgumentParser()
p.add_argument('--order-id', required=True, help="the pending order's own order_id (from pending_live_orders.json / the proposal notification)")
p.add_argument('--robinhood-order-id', required=True, help="order id returned by place_option_order for the entry buy")
p.add_argument('--stop-order-id', default=None, help="order id returned by place_option_order for the protective stop_market sell")
p.add_argument('--fill-price', type=float, default=None, help="actual average fill price if known; falls back to the pending order's limit_price")
p.add_argument('--notes', default=None)
args = p.parse_args()

if not os.path.exists(PENDING_PATH):
    print(f"ERROR: {PENDING_PATH} does not exist -- nothing to mark executed")
    sys.exit(1)

orders = json.load(open(PENDING_PATH))
match = next((o for o in orders if o.get('order_id') == args.order_id), None)
if match is None:
    print(f"ERROR: no order with order_id={args.order_id!r} found in {PENDING_PATH}")
    sys.exit(1)
if match.get('status') != 'awaiting_confirmation':
    print(f"WARNING: order {args.order_id} has status {match.get('status')!r}, not 'awaiting_confirmation' -- "
          f"logging the execution anyway since you've confirmed it happened, but double check this is the order you meant.")

fill_price = args.fill_price if args.fill_price is not None else match.get('limit_price')

match['status'] = 'confirmed_executed'
match['executed_at_utc'] = datetime.now(timezone.utc).isoformat()
match['robinhood_order_id'] = args.robinhood_order_id
match['stop_order_id'] = args.stop_order_id
match['actual_fill_price'] = fill_price
if args.notes:
    match['execution_notes'] = args.notes

json.dump(orders, open(PENDING_PATH, 'w'), indent=2)

append_event(
    "order_confirmed_executed",
    order_id=args.order_id, symbol=match.get('symbol'), direction=match.get('direction'),
    strike=match.get('strike'), expiration=match.get('expiration'),
    robinhood_order_id=args.robinhood_order_id, stop_order_id=args.stop_order_id,
    fill_price=fill_price, planned_hard_stop_price=match.get('planned_hard_stop_price'),
    notes=args.notes,
)

print(f"LOGGED: order {args.order_id} ({match.get('symbol')} {match.get('direction')} "
      f"${match.get('strike')} exp {match.get('expiration')}) marked confirmed_executed.")
print(f"Entry fill ${fill_price:.2f}, protective stop @ ${match.get('planned_hard_stop_price'):.2f} "
      f"(order id {args.stop_order_id or 'not recorded'}).")
print("Remember to log the eventual closure with live_log_position_closed.py once this position exits.")
