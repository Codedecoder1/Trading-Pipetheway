"""
Given a Layer-1-passing signal plus live data the calling session has
already fetched, runs the full risk gate (live_risk_checks.py) and, only
if everything passes, appends a proposed order to pending_live_orders.json
for human confirmation.

Contract selection (REVISION 10, 2026-08-27): the calling session no
longer just grabs "the ATM contract" blind. It should first call
contract_selector.select_contract() on the nearest expiration's full
contract list -- that tries ATM first and, if ATM's ask*100 exceeds the
$140 cap, steps down to a 0.25-0.35 delta OTM contract that fits under
the cap before giving up. Whatever that function returns (or the ATM
contract directly, if it fits) is what gets passed in here via --strike/
--option-id/--ask/--bid. This script re-validates affordability itself
either way (live_risk_checks.check_affordability, inside run_all_checks
below) -- contract_selector's job is picking a better candidate, not
replacing the final gate.

Execution cutoff (REVISION 10, 2026-08-27): before any risk check runs,
this script now also checks --signal-timestamp against
contract_filters.EXECUTION_CUTOFF (19:30:00 UTC) via check_execution_time().
This is DELIBERATELY separate from and tighter than Layer 1's own
session_time check (SESSION_TIME_CUTOFF, 20:00:00 UTC) -- a signal can be
correctly detected and logged up to 20:00:00 UTC, but only auto-executed
up to 19:30:00 UTC, because a later entry has no same-day option data
left to manage the exit plan against (see contract_filters.py's REVISION
10 docstring note for the full reasoning). A signal that fails this gate
is logged as signal-only (event "signal_only_not_executed") and the
function returns before any risk check or contract-selection concern is
even evaluated -- it's not a rejection of the signal or the contract,
there just isn't session time left to manage the trade.

This script NEVER calls place_option_order or review_option_order itself
-- it has no tool access at all, it's pure Python. review_option_order is
called by the orchestrating session BEFORE this script runs (to get the
real alerts), and its result is passed in via --review-alerts.

Dynamic risk sizing (REVISION 11, 2026-08-28): --buying-power and
--total-equity are new. Pass the account's live numbers (from
get_portfolio) and the affordability/drawdown thresholds inside
run_all_checks are computed live (85% of buying power / 15% of equity)
instead of using the old fixed $140/-$21 constants -- see
live_risk_checks.py's REVISION 1 docstring. Both are optional; omitting
either falls back to the static constants, which is only meant for
testing this script in isolation -- the live pipeline should always pass
both.

VIX market-regime sizing (REVISION 12, 2026-08-30), per explicit user
request, shared by BOTH live strategies since this script (and
live_risk_checks.py underneath it) is what both the SMC and VWAP/DMI
Wednesday pipelines call. --vix is optional: pass the live VIX reading
(mcp__RBH__get_index_quotes, instrument_id
3b912aa2-88f9-4682-8ae3-e39520bdf4db) and run_all_checks() applies the
regime-adjusted budget (halved when VIX > 25.0) and the classification is
both stored on the order (risk_checks.regime) and printed in the
notification text below the existing "Sizing (live): ..." line. Omitting
it leaves behavior exactly as before REVISION 12.

Usage (all args required except --buying-power/--total-equity):
  python3 live_prepare_order.py \
    --symbol AAPL --direction call --strike 230.0 --expiration 2026-08-28 \
    --option-id <uuid> --ask 0.85 --bid 0.80 \
    --open-positions 0 --today-pnl 0.0 --signal-timestamp "2026-08-26 14:45:00+00:00" \
    --review-alerts "<free text from review_option_order, or 'none'>" \
    --buying-power 177.42 --total-equity 177.42

Prints one of:
  "PREPARED: <order id>" plus the exact notification text to send,
  "REJECTED: <reasons>" with nothing written, or
  "SIGNAL_ONLY: <reason>" (fired after EXECUTION_CUTOFF -- logged, not executed).
"""
import argparse, json, os, uuid
from datetime import datetime, timezone
import sys
sys.path.insert(0, '/home/claude/smc_bot')
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from live_risk_checks import run_all_checks, compute_hard_stop_price
from trade_log import append_event
from contract_filters import check_execution_time, EXECUTION_CUTOFF

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
PENDING_PATH = os.path.join(BACKTEST_DIR, 'pending_live_orders.json')

p = argparse.ArgumentParser()
p.add_argument('--symbol', required=True)
p.add_argument('--direction', required=True, choices=['call', 'put'])
p.add_argument('--strike', required=True, type=float)
p.add_argument('--expiration', required=True)
p.add_argument('--option-id', required=True)
p.add_argument('--ask', required=True, type=float)
p.add_argument('--bid', required=True, type=float)
p.add_argument('--open-positions', required=True, type=int)
p.add_argument('--today-pnl', required=True, type=float)
p.add_argument('--signal-timestamp', required=True)
p.add_argument('--review-alerts', default='none')
p.add_argument('--selection-method', default='ATM',
                help='"ATM" or "OTM_DELTA" -- whatever contract_selector.select_contract() '
                     'returned as its method; informational, logged with the proposal.')
p.add_argument('--buying-power', type=float, default=None,
                help='REVISION 11: current live buying power (from get_portfolio). Drives the '
                     'dynamic affordability threshold (85%% of this). Omit to use the static $140 fallback.')
p.add_argument('--total-equity', type=float, default=None,
                help='REVISION 11: current live total account equity (from get_portfolio). Drives the '
                     'dynamic daily-drawdown cap (15%% of this). Omit to use the static -$21 fallback.')
p.add_argument('--vix', type=float, default=None,
                help='REVISION 12 (2026-08-30): current live VIX reading (mcp__RBH__get_index_quotes, '
                     'instrument_id 3b912aa2-88f9-4682-8ae3-e39520bdf4db). Halves the contract budget '
                     'when VIX > 25.0. Omit to leave sizing regime-unaware, as before REVISION 12.')
args = p.parse_args()

# REVISION 10: execution cutoff, checked BEFORE any risk check or
# contract-selection concern. Separate from and tighter than Layer 1's
# own session_time gate -- see module docstring above.
exec_ok, exec_note = check_execution_time(args.signal_timestamp)
if not exec_ok:
    append_event(
        "signal_only_not_executed",
        symbol=args.symbol, direction=args.direction, strike=args.strike,
        expiration=args.expiration, ask=args.ask, bid=args.bid,
        signal_timestamp=args.signal_timestamp, execution_cutoff=EXECUTION_CUTOFF,
        note=exec_note,
    )
    print(f"SIGNAL_ONLY: {exec_note}")
    sys.exit(0)

all_pass, results = run_all_checks(
    ask_price=args.ask, bid_price=args.bid,
    open_position_count=args.open_positions, today_pnl_dollars=args.today_pnl,
    buying_power=args.buying_power, total_equity=args.total_equity, vix=args.vix,
)

if not all_pass:
    # NOTE (fixed 2026-08-30): results also carries non-check metadata keys
    # ('sizing', and now 'regime') that don't have an 'ok' field -- this used
    # to blow up with a bare KeyError on any real rejection, since 'sizing'
    # has been in results since REVISION 1 (2026-08-28) and this path was
    # apparently never exercised end-to-end until the REVISION 2 VIX testing
    # surfaced it. Restrict to entries that are actually pass/fail checks.
    failed = {check: r['note'] for check, r in results.items()
              if isinstance(r, dict) and 'ok' in r and not r['ok']}
    append_event(
        "proposal_rejected",
        symbol=args.symbol, direction=args.direction, strike=args.strike,
        expiration=args.expiration, ask=args.ask, bid=args.bid,
        signal_timestamp=args.signal_timestamp, failed_checks=failed,
    )
    print("REJECTED:")
    for check, r in results.items():
        if isinstance(r, dict) and 'ok' in r and not r['ok']:
            print(f"  FAILED {check}: {r['note']}")
    regime = results.get("regime")
    if regime:
        print(f"  (market regime: {regime['regime']}, VIX {regime['vix']:.2f} -- {regime['note']})")
    sys.exit(0)

order_id = str(uuid.uuid4())
hard_stop_price = compute_hard_stop_price(args.ask)
order = {
    "order_id": order_id,
    "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
    "signal_timestamp": args.signal_timestamp,
    "symbol": args.symbol,
    "direction": args.direction,
    "option_type": "call" if args.direction == "call" else "put",
    "strike": args.strike,
    "expiration": args.expiration,
    "option_id": args.option_id,
    "side": "buy",
    "position_effect": "open",
    "quantity": 1,
    "limit_price": args.ask,
    "bid_at_prep": args.bid,
    "planned_hard_stop_price": hard_stop_price,
    "planned_hard_stop_type": "stop_market",
    "planned_hard_stop_time_in_force": "gtc",
    "risk_checks": results,
    "review_alerts": args.review_alerts,
    "selection_method": args.selection_method,
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
    "proposal_prepared",
    order_id=order_id, symbol=args.symbol, direction=args.direction,
    strike=args.strike, expiration=args.expiration, option_id=args.option_id,
    limit_price=args.ask, bid_at_prep=args.bid,
    planned_hard_stop_price=hard_stop_price,
    signal_timestamp=args.signal_timestamp, review_alerts=args.review_alerts,
    selection_method=args.selection_method,
)

print(f"PREPARED: {order_id}")
print("\n--- Notification text ---")
print(f"SIGNAL: {args.symbol} {args.direction.upper()} ${args.strike} exp {args.expiration}")
print(f"Limit BUY 1 contract @ ${args.ask:.2f} (${args.ask*100:.2f} total). "
      f"Bid ${args.bid:.2f}. Planned GTC stop-loss @ ${hard_stop_price:.2f} (-15%).")
print(f"Signal fired {args.signal_timestamp}. Order id {order_id}.")
print("")
print("STOP-LOSS -- place this immediately after the entry fills:")
print(f"  {args.direction.upper()} to SELL / close: 1x {args.symbol} ${args.strike} "
      f"{args.direction} exp {args.expiration}")
print(f"  Order type   : stop-market (stop loss)")
print(f"  Stop (trigger): ${hard_stop_price:.2f}   (entry ask ${args.ask:.2f} minus 15%, rounded to the cent)")
print(f"  Time in force: GTC")
print(f"  Option id    : {args.option_id}")
sizing = results.get("sizing", {})
if sizing.get("dynamic"):
    print(f"Sizing (live): budget ${sizing['max_premium']:.2f} from ${sizing['buying_power']:.2f} buying power, "
          f"drawdown cap ${sizing['drawdown_cap']:.2f} from ${sizing['total_equity']:.2f} equity.")
regime = results.get("regime")
if regime:
    print(f"Market regime: {regime['regime']} (VIX {regime['vix']:.2f}) -- {regime['note']}.")
print(f"Review alerts: {args.review_alerts}")
print("Reply with the order id (or \"yes, execute <symbol>\") in your session with Claude to confirm and place it. "
      "Nothing executes until you do -- and price/spread will be re-checked fresh at confirmation time before anything is submitted.")
