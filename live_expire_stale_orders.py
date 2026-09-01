"""
Marks any pending_live_orders.json entry still "awaiting_confirmation" and
older than STALE_MINUTES as "expired". Run at the START of every scheduled
firing, before preparing any new order, so a proposal from an hour ago
can never get silently confirmed against a price that's no longer real.
"""
import json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from trade_log import append_event

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
PENDING_PATH = os.path.join(BACKTEST_DIR, 'pending_live_orders.json')
STALE_MINUTES = 15

if not os.path.exists(PENDING_PATH):
    print("no pending_live_orders.json yet -- nothing to expire")
else:
    orders = json.load(open(PENDING_PATH))
    now = datetime.now(timezone.utc)
    n_expired = 0
    for o in orders:
        if o.get('status') != 'awaiting_confirmation':
            continue
        prepared_at = datetime.fromisoformat(o['prepared_at_utc'])
        age_min = (now - prepared_at).total_seconds() / 60
        if age_min > STALE_MINUTES:
            o['status'] = 'expired'
            o['expired_reason'] = f"unconfirmed for {age_min:.0f} min (limit {STALE_MINUTES})"
            n_expired += 1
            append_event(
                "order_expired", order_id=o.get('order_id'), symbol=o.get('symbol'),
                direction=o.get('direction'), strike=o.get('strike'),
                expiration=o.get('expiration'), limit_price=o.get('limit_price'),
                age_minutes=round(age_min, 1),
            )
    json.dump(orders, open(PENDING_PATH, 'w'), indent=2)
    still_pending = sum(1 for o in orders if o['status'] == 'awaiting_confirmation')
    print(f"expired {n_expired} stale order(s); {still_pending} still awaiting_confirmation")
