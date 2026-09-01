"""
CLI wrapper around contract_selector.select_contract(), for the live
signal-monitor trigger to call directly (REVISION 10, 2026-08-27) instead
of hardcoding "always pick ATM" the way the original trigger prompt did.

REVISION 1 (2026-08-28): --max-premium is no longer the primary way to set
the budget. Pass --buying-power (the account's current live buying power,
from get_portfolio) instead and this script derives the budget itself via
the same dynamic sizing contract_selector.py uses (85% of buying power).
--max-premium still works as an explicit override/fallback for testing --
if both are given, --max-premium wins.

REVISION 3 (2026-08-30): optional --vix, forwarded to select_contract() so
contract selection is checked against the same VIX-regime-adjusted budget
the final risk gate (live_prepare_order.py) will apply -- see
live_risk_checks.py's REVISION 2 docstring for the full VIX feature.

Usage (dynamic, live pipeline):
  python3 resolve_contract.py --direction call --buying-power 177.42 --contracts-json '[
    {"strike": 145.0, "ask": 4.45, "bid": 4.35, "delta": 0.50, "option_id": "..."},
    {"strike": 150.0, "ask": 2.10, "bid": 2.00, "delta": 0.31, "option_id": "..."}
  ]'
(or --contracts-file <path to the same JSON array>, if it's easier for the
calling session to write a file than to inline the JSON on the command line)

Prints one line of JSON: {"method": "ATM"|"OTM_DELTA"|"REJECTED_NO_AFFORDABLE_CONTRACT",
"note": "...", "contract": {...} or null}. Exit code is always 0 -- a
rejection is a valid, expected outcome, not a script error; the caller
checks the "method" field.
"""
import argparse, json, sys
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from contract_selector import select_contract

p = argparse.ArgumentParser()
p.add_argument('--direction', required=True, choices=['call', 'put'])
p.add_argument('--contracts-json', help='JSON array of {strike, ask, bid, delta, option_id} inline')
p.add_argument('--contracts-file', help='path to a JSON file containing the same array')
p.add_argument('--buying-power', type=float, default=None,
                help='current live buying power (from get_portfolio) -- budget is derived as 85%% of this')
p.add_argument('--max-premium', type=float, default=None,
                help='explicit budget override; skips the dynamic calculation. Falls back to the static '
                     '$140 constant if neither this nor --buying-power is given.')
p.add_argument('--vix', type=float, default=None,
                help='REVISION 3 (2026-08-30): current live VIX reading (mcp__RBH__get_index_quotes, '
                     'instrument_id 3b912aa2-88f9-4682-8ae3-e39520bdf4db). Forwarded so the budget used '
                     'here matches the regime-adjusted budget the risk gate will apply. No effect if '
                     '--max-premium is given.')
args = p.parse_args()

if not args.contracts_json and not args.contracts_file:
    print(json.dumps({"method": "ERROR", "note": "must pass --contracts-json or --contracts-file", "contract": None}))
    sys.exit(0)

if args.contracts_file:
    contracts = json.load(open(args.contracts_file))
else:
    contracts = json.loads(args.contracts_json)

contract, method, note = select_contract(contracts, args.direction,
                                          max_premium=args.max_premium, buying_power=args.buying_power,
                                          vix=args.vix)
print(json.dumps({"method": method, "note": note, "contract": contract}))
