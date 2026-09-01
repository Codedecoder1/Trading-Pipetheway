"""
CLI wrapper for resolving ONE leg of a Pairs Stat-Arb proposal to a single
tradeable contract (REVISION 1, 2026-08-31, built from the user's own
"Native Robinhood Engine 3 Pipeline" sketch -- resolve_robinhood_option_leg()
-- adapted to fit this codebase's actual architecture).

Why this differs from the user's sketch: the sketch's resolve_robinhood_option_leg()
takes an `rh_client` object and calls rh_client.get_option_chain(...) /
rh_client.get_option_market_data(...) directly inside the function. There is
no such client object in this pipeline -- the calling session (a trigger
firing) makes those calls itself via the real MCP tools
(mcp__RBH__get_option_chains, mcp__RBH__get_option_instruments,
mcp__RBH__get_option_quotes), same as every other script in this codebase
(contract_selector.py/resolve_contract.py never touch the network either).
This script only does the pure-Python part: given a pre-fetched list of
candidate contracts for ONE already-chosen expiration + option type, pick
the best one under budget. It has no tool access, matching every other
resolve/prepare script here.

Selection rule (matches the user's spec exactly): among contracts priced in
[min_premium/100, max_leg_budget/100] per share, pick the one with the
highest open_interest (most liquid, fastest to execute) -- NOT a delta-band
pick like contract_selector.py uses for the single-leg strategies. Pairs
legs are a defined-risk directional bet sized by premium budget, not a
delta-targeted trend entry, so liquidity is the tie-breaker here instead.

Usage:
  python3 resolve_pairs_leg.py --leg-label leg_1 --symbol AMD --option-type call \
    --expiration 2026-09-18 --max-leg-budget 21.25 --contracts-file /tmp/leg1_contracts.json

--contracts-file / --contracts-json: JSON array of
  {"strike": <float>, "ask": <float>, "bid": <float>, "option_id": <str>, "open_interest": <int>}
(same per-contract shape mcp__RBH__get_option_quotes results are already
being reshaped into for the single-leg pipeline -- open_interest additionally
required here, which get_option_instruments/get_option_quotes both return).

Prints one line of JSON:
  {"method": "OI_RANKED"|"REJECTED_NO_AFFORDABLE_CONTRACT", "note": "...",
   "contract": {...}|null}
Exit code is always 0 -- a rejection is an expected outcome, not a script error.
"""
import argparse, json, sys
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from live_risk_checks import MIN_PREMIUM_TOTAL, get_max_contract_budget

p = argparse.ArgumentParser()
p.add_argument('--leg-label', required=True, help='e.g. "leg_1" or "leg_2", carried through to the output for logging')
p.add_argument('--symbol', required=True)
p.add_argument('--option-type', required=True, choices=['call', 'put'])
p.add_argument('--expiration', required=True)
p.add_argument('--buying-power', type=float, default=None,
                help='current live buying power (from get_portfolio). Preferred way to set the leg '
                     'budget: derived as get_max_contract_budget(buying_power, vix) / 2, i.e. half the '
                     'SAME dynamic package budget pairs_prepare_order.py will re-check later. Pass this '
                     '(and --vix, if available) rather than --max-leg-budget on the live pipeline.')
p.add_argument('--vix', type=float, default=None,
                help='current live VIX reading, forwarded into get_max_contract_budget() for regime sizing.')
p.add_argument('--max-leg-budget', type=float, default=None,
                help='explicit override for the leg budget -- if given, wins over --buying-power/--vix. '
                     'Mainly for standalone testing; the live pipeline should pass --buying-power instead.')
p.add_argument('--min-premium', type=float, default=MIN_PREMIUM_TOTAL,
                help=f'dollar floor for this leg (default ${MIN_PREMIUM_TOTAL:.2f}, same fixed '
                     'lottery-ticket floor used everywhere else in this pipeline).')
p.add_argument('--contracts-json', help='JSON array of {strike, ask, bid, option_id, open_interest} inline')
p.add_argument('--contracts-file', help='path to a JSON file containing the same array')
args = p.parse_args()

if args.max_leg_budget is not None:
    leg_budget = args.max_leg_budget
elif args.buying_power is not None:
    leg_budget = get_max_contract_budget(args.buying_power, vix=args.vix) / 2.0
else:
    print(json.dumps({"method": "REJECTED_NO_AFFORDABLE_CONTRACT",
                       "note": "no --max-leg-budget or --buying-power given -- cannot determine a budget",
                       "contract": None}))
    sys.exit(0)

if args.contracts_file:
    contracts = json.load(open(args.contracts_file))
elif args.contracts_json:
    contracts = json.loads(args.contracts_json)
else:
    print(json.dumps({"method": "REJECTED_NO_AFFORDABLE_CONTRACT",
                       "note": "no --contracts-file or --contracts-json given", "contract": None}))
    sys.exit(0)

min_ask = args.min_premium / 100.0
max_ask = leg_budget / 100.0

candidates = []
for c in contracts:
    ask = float(c.get("ask", 0.0))
    bid = float(c.get("bid", 0.0))
    if bid <= 0 or ask <= 0:
        continue
    if min_ask <= ask <= max_ask:
        candidates.append({
            "leg_label": args.leg_label,
            "symbol": args.symbol,
            "option_type": args.option_type,
            "expiration": args.expiration,
            "strike": float(c["strike"]),
            "option_id": c.get("option_id") or c.get("instrument_id"),
            "bid": bid,
            "ask": ask,
            "open_interest": int(c.get("open_interest", 0)),
            "total_leg_cost": round(ask * 100.0, 2),
        })

if not candidates:
    print(json.dumps({
        "method": "REJECTED_NO_AFFORDABLE_CONTRACT",
        "note": f"no {args.symbol} {args.option_type} contract at {args.expiration} priced in "
                f"[${args.min_premium:.2f}, ${leg_budget:.2f}] (checked {len(contracts)} contract(s))",
        "contract": None,
    }))
    sys.exit(0)

candidates.sort(key=lambda x: x["open_interest"], reverse=True)
winner = candidates[0]
print(json.dumps({
    "method": "OI_RANKED",
    "note": f"{len(candidates)} contract(s) fit the ${args.min_premium:.2f}-${leg_budget:.2f} "
            f"window; picked highest open interest ({winner['open_interest']})",
    "contract": winner,
}))
