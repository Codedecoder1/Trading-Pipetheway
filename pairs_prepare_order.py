"""
Given a Pairs Stat-Arb signal (from pairs_arb_scanner.py) plus two already-
resolved leg contracts (from resolve_pairs_leg.py, run once per leg by the
calling session), runs the combined two-leg risk gate and, only if
everything passes, appends ONE package proposal to pending_live_orders.json
for human confirmation -- the two-leg analogue of live_prepare_order.py.

REVISION 1 (2026-08-31), built from the user's own "Native Robinhood Engine
3 Pipeline" sketch (pairs_pipeline.py), adapted to fit this codebase's real
architecture and conventions. Three deliberate corrections from that sketch,
each explained here so they don't look like they were missed:

  1. NO rh_client / direct network calls. The sketch's
     resolve_robinhood_option_leg() called rh_client.get_option_chain(...)
     and rh_client.get_option_market_data(...) directly. This script (like
     every other script in this pipeline) has NO tool access at all -- the
     calling session (the live trigger) fetches chains/quotes itself via
     the real MCP tools (mcp__RBH__get_option_chains,
     mcp__RBH__get_option_instruments, mcp__RBH__get_option_quotes) and
     passes the results in via resolve_pairs_leg.py, then this script.

  2. DYNAMIC package budget, not a fixed $42.50. The sketch hardcoded
     TOTAL_ACCOUNT_CAPITAL=$170 and MAX_PACKAGE_RISK_CAP=$42.50 as module
     constants. This account's live balance moves (it was ~$168 on 2026-08-24,
     ~$177 by 2026-08-28) -- exactly the problem REVISION 4 of
     live_risk_checks.py already solved for the single-leg strategies by
     deriving the budget from live buying_power instead of a snapshot. This
     script reuses that SAME function, get_max_contract_budget(buying_power,
     vix), for the package cap, then splits it 50/50 into two leg budgets --
     preserving the sketch's actual design intent (half the package risk per
     leg) while keeping the number correct as the account grows or shrinks.
     It also inherits VIX-regime sizing (halved budget when VIX > 25.0) for
     free, same as SMC/VWAP already get.

  3. APPEND, not overwrite, to pending_live_orders.json. The sketch's
     run_robinhood_pairs_pipeline() did `json.dump([trade_proposal], f)` --
     that would have silently wiped out any existing SMC or VWAP/DMI
     proposal already sitting in that SHARED file. This script loads the
     existing list, appends the new package entry, and writes the whole
     list back, exactly like live_prepare_order.py does.

The written entry is a single PACKAGE-level object (not two separate
per-leg rows) with a nested "legs" array, so live_expire_stale_orders.py's
existing sweep (which only looks at top-level "status"/"prepared_at_utc")
still expires it correctly after 15 minutes unconfirmed, and SMC/VWAP's own
"is there already an awaiting_confirmation order" check still sees it and
backs off -- a pairs package counts as the one allowed open position, same
as the original design intent (both legs together = one position).

This script NEVER calls place_option_order or review_option_order itself --
review_option_order (SIMULATE ONLY) is called by the orchestrating session,
once per leg, BEFORE this script runs, and passed in via
--leg1-review-alerts/--leg2-review-alerts.

Usage:
  python3 pairs_prepare_order.py \
    --pair AMD/NVDA --direction LONG_A_SHORT_B --z-score -2.15 --p-value 0.041 \
    --hedge-ratio 1.34 --signal-timestamp "2026-08-31 14:30:00+00:00" \
    --leg1-json '{"symbol":"AMD","option_type":"call","expiration":"2026-09-18","strike":150.0,"option_id":"...","ask":0.18,"bid":0.16}' \
    --leg2-json '{"symbol":"NVDA","option_type":"put","expiration":"2026-09-18","strike":115.0,"option_id":"...","ask":0.19,"bid":0.17}' \
    --open-positions 0 --today-pnl 0.0 --buying-power 177.42 --total-equity 177.42 --vix 14.43

Prints one of:
  "PREPARED: <package id>" plus the notification text to send,
  "REJECTED: <reasons>" with nothing written.
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone

sys.path.insert(0, '/home/claude/smc_bot')
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from live_risk_checks import (
    get_max_contract_budget, get_max_daily_drawdown, get_market_regime,
    check_premium_floor, check_spread, check_position_cap, check_daily_drawdown,
)
from pairs_arb_scanner import check_pairs_affordability
from trade_log import append_event

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
PENDING_PATH = os.path.join(BACKTEST_DIR, 'pending_live_orders.json')

p = argparse.ArgumentParser()
p.add_argument('--pair', required=True, help='e.g. "AMD/NVDA"')
p.add_argument('--direction', required=True, choices=['LONG_A_SHORT_B', 'SHORT_A_LONG_B'])
p.add_argument('--z-score', required=True, type=float)
p.add_argument('--p-value', required=True, type=float)
p.add_argument('--hedge-ratio', required=True, type=float)
p.add_argument('--signal-timestamp', required=True)
p.add_argument('--leg1-json', required=True, help='JSON object from resolve_pairs_leg.py\'s "contract" field, leg 1')
p.add_argument('--leg2-json', required=True, help='JSON object from resolve_pairs_leg.py\'s "contract" field, leg 2')
p.add_argument('--leg1-review-alerts', default='none')
p.add_argument('--leg2-review-alerts', default='none')
p.add_argument('--open-positions', required=True, type=int,
                help='shared across ALL THREE strategies (get_option_positions, nonzero=true) -- '
                     'a pairs package counts as the one allowed open position.')
p.add_argument('--today-pnl', required=True, type=float)
p.add_argument('--buying-power', required=True, type=float)
p.add_argument('--total-equity', required=True, type=float)
p.add_argument('--vix', type=float, default=None)
args = p.parse_args()

leg1 = json.loads(args.leg1_json)
leg2 = json.loads(args.leg2_json)

# --- Dynamic package/leg budget (correction #2 in the module docstring) ---
package_budget = get_max_contract_budget(args.buying_power, vix=args.vix)
leg_budget = package_budget / 2.0
regime = get_market_regime(args.vix) if args.vix is not None else None

leg1_ask, leg1_bid = float(leg1['ask']), float(leg1['bid'])
leg2_ask, leg2_bid = float(leg2['ask']), float(leg2['bid'])

floor1_ok, floor1_note = check_premium_floor(leg1_ask)
floor2_ok, floor2_note = check_premium_floor(leg2_ask)
spread1_ok, spread1_note = check_spread(leg1_bid, leg1_ask)
spread2_ok, spread2_note = check_spread(leg2_bid, leg2_ask)
package_ok, package_note, leg1_cost, leg2_cost = check_pairs_affordability(
    leg1_ask, leg2_ask, max_leg_premium=leg_budget, max_package_premium=package_budget)
pos_ok, pos_note = check_position_cap(args.open_positions)
drawdown_cap = -get_max_daily_drawdown(args.total_equity)
dd_ok, dd_note = check_daily_drawdown(args.today_pnl, cap=drawdown_cap)

checks = {
    "leg1_premium_floor": {"ok": floor1_ok, "note": floor1_note},
    "leg2_premium_floor": {"ok": floor2_ok, "note": floor2_note},
    "leg1_spread": {"ok": spread1_ok, "note": spread1_note},
    "leg2_spread": {"ok": spread2_ok, "note": spread2_note},
    "package_affordability": {"ok": package_ok, "note": package_note},
    "position_cap": {"ok": pos_ok, "note": pos_note},
    "daily_drawdown": {"ok": dd_ok, "note": dd_note},
}
all_pass = all(c["ok"] for c in checks.values())

sizing = {
    "package_budget": round(package_budget, 2),
    "leg_budget": round(leg_budget, 2),
    "buying_power": args.buying_power,
    "total_equity": args.total_equity,
    "drawdown_cap": round(drawdown_cap, 2),
}

if not all_pass:
    failed = {k: v['note'] for k, v in checks.items() if not v['ok']}
    append_event(
        "proposal_rejected", strategy="PAIRS_STAT_ARBITRAGE", pair=args.pair,
        direction=args.direction, z_score=args.z_score, p_value=args.p_value,
        signal_timestamp=args.signal_timestamp, failed_checks=failed,
    )
    print("REJECTED:")
    for k, v in checks.items():
        if not v['ok']:
            print(f"  FAILED {k}: {v['note']}")
    if regime:
        print(f"  (market regime: {regime['regime']}, VIX {regime['vix']:.2f} -- {regime['note']})")
    sys.exit(0)

package_id = str(uuid.uuid4())
total_package_cost = round(leg1_cost + leg2_cost, 2)
order = {
    "order_id": package_id,
    "engine": "PAIRS_STAT_ARBITRAGE",
    "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
    "signal_timestamp": args.signal_timestamp,
    "pair": args.pair,
    "symbol": args.pair,  # convenience alias so live_expire_stale_orders.py's logging stays informative
    "direction": args.direction,
    "signal_metrics": {
        "z_score": args.z_score,
        "adf_p_value_approx": args.p_value,
        "hedge_ratio": args.hedge_ratio,
        "exit_target": "Z_SCORE = 0.0",
        "stop_loss": "Z_SCORE = +/-3.5",
    },
    "legs": [
        {**leg1, "leg_label": "leg_1", "side": "buy", "position_effect": "open", "quantity": 1,
         "limit_price": leg1_ask, "total_leg_cost": leg1_cost, "review_alerts": args.leg1_review_alerts},
        {**leg2, "leg_label": "leg_2", "side": "buy", "position_effect": "open", "quantity": 1,
         "limit_price": leg2_ask, "total_leg_cost": leg2_cost, "review_alerts": args.leg2_review_alerts},
    ],
    "total_package_cost": total_package_cost,
    "account_budget_used_pct": round((total_package_cost / args.buying_power) * 100, 2) if args.buying_power else None,
    "risk_checks": checks,
    "sizing": sizing,
    "regime": regime,
    "status": "awaiting_confirmation",
}

existing = []
if os.path.exists(PENDING_PATH):
    try:
        existing = json.load(open(PENDING_PATH))
    except Exception:
        existing = []
existing.append(order)
json.dump(existing, open(PENDING_PATH, 'w'), indent=2)

append_event(
    "proposal_prepared", strategy="PAIRS_STAT_ARBITRAGE", order_id=package_id, pair=args.pair,
    direction=args.direction, z_score=args.z_score, p_value=args.p_value,
    leg1_symbol=leg1['symbol'], leg1_strike=leg1['strike'], leg1_option_id=leg1['option_id'],
    leg2_symbol=leg2['symbol'], leg2_strike=leg2['strike'], leg2_option_id=leg2['option_id'],
    total_package_cost=total_package_cost, signal_timestamp=args.signal_timestamp,
)

print(f"PREPARED: {package_id}")
print("\n--- Notification text ---")
print(f"PAIRS SIGNAL: {args.pair} [{args.direction}] Z={args.z_score:.2f} p={args.p_value:.4f}")
print(f"Leg 1: {leg1['symbol']} {leg1['option_type'].upper()} ${leg1['strike']} exp {leg1['expiration']} "
      f"-- BUY 1 @ ${leg1_ask:.2f} (${leg1_cost:.2f} total), bid ${leg1_bid:.2f}")
print(f"Leg 2: {leg2['symbol']} {leg2['option_type'].upper()} ${leg2['strike']} exp {leg2['expiration']} "
      f"-- BUY 1 @ ${leg2_ask:.2f} (${leg2_cost:.2f} total), bid ${leg2_bid:.2f}")
print(f"Total package cost ${total_package_cost:.2f} ({sizing['buying_power'] and round(total_package_cost/sizing['buying_power']*100,1)}% of buying power). "
      f"Exit target Z=0.0, stop-loss Z=+/-3.5 (manual -- no price-based hard stop on a pairs package).")
print(f"Signal fired {args.signal_timestamp}. Package id {package_id}.")
print(f"Sizing (live): package budget ${sizing['package_budget']:.2f} (${sizing['leg_budget']:.2f}/leg) "
      f"from ${sizing['buying_power']:.2f} buying power, drawdown cap ${sizing['drawdown_cap']:.2f} "
      f"from ${sizing['total_equity']:.2f} equity.")
if regime:
    print(f"Market regime: {regime['regime']} (VIX {regime['vix']:.2f}) -- {regime['note']}.")
print(f"Leg 1 review alerts: {args.leg1_review_alerts}")
print(f"Leg 2 review alerts: {args.leg2_review_alerts}")
print("This is a TWO-LEG package -- both legs need to be placed together on the Robinhood app to "
      "match this proposal. Reply with the package id (or \"yes, execute the <pair> pairs trade\") in "
      "your session with Claude to confirm and place both legs. Nothing executes until you do -- and "
      "price/spread will be re-checked fresh at confirmation time before anything is submitted.")
