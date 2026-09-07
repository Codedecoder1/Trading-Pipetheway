"""
exit_manager.py -- the live exit tier (2026-09-07, per explicit user request;
see docs/EXIT_SPEC.md section 5). STATELESS rewrite (2026-09-07): every
scheduled firing runs in a fresh, empty container that shares NO filesystem
with any other firing or task, so this module keeps NO local state. Phase
(pre-TP1 vs runner) and de-duplication are reconstructed from the broker
account, which the orchestrating session passes in.

WHAT IT IS. A pure evaluator, same discipline as live_prepare_order.py: NO
broker/order tools are called or reachable from here. The orchestrating
scheduled session fetches open positions, their quotes, and their recent
order history via the MCP tools and passes the numbers in. This module
decides which positions to close and prints a **close proposal ticket**.
It never places a closing order and writes no state file.

HOW THE BRACKET CHANGES THIS. Every confirmed entry now places THREE orders
(see docs/ENTRY_SPEC.md): the buy, a resting -10% stop-market (GTC), and a
resting +30% limit (GTC). When both of those rest at the broker, the two
most time-critical exits happen on their own -- so this monitor's job is
the gaps: a missing bracket, a broken thesis, a dead trade, the end-of-day
flatten, and a runner that has round-tripped back to breakeven.

WHEN IT RUNS. Its own scheduled task ("Exit Monitor"). Because a single
scheduled task cannot fire more than hourly, this is fanned out to a small
number of offset hourly tasks (2 is plenty now that the bracket carries the
fast exits -- see SCHEDULED_TASK_UPDATES.md).

RULES (per position, first match wins -- priority order):
  1. STOP_UNPROTECTED   mark <= entry*(1-HARD_STOP_PCT) AND no resting stop
                        -> close 100% now, and place a resting stop on anything
                        else that is missing one
  2. EOD_FLATTEN        within EOD_FLATTEN_MIN of the session close, open
                        -> close 100%
  3. THESIS_BREAK       orchestrator set thesis_broken                -> close 100%
  4. CONSOLIDATION      orchestrator set underlying_consolidating     -> close 100%
  5. TAKE_PROFIT_1      not tp1_filled, no resting TP, mark >= entry*(1+TAKE_PROFIT_PCT)
                        -> close TP fraction (whole 1-lot); move the stop on the
                        rest to breakeven
  6. RUNNER_GIVEBACK    tp1_filled and mark <= entry (round-tripped to breakeven)
                        -> close the remainder
  7. DEAD_TRADE         not tp1_filled, >= DEAD_TRADE_MIN in trade, |mark/entry-1|
                        <= DEAD_TRADE_BAND                            -> close 100%

Rules 1 and 5 only fire when the corresponding resting order is MISSING --
when the bracket is in place the broker handles those, and proposing a
duplicate would be noise. `has_pending_close` suppresses a proposal for a
position that already has a close order working.

PAIRS (evaluate_pairs_exits): |z| <= Z_EXIT_TARGET target / |z| >= Z_EXIT_ABANDON
abandon / EOD flatten -- close both legs. A pair with has_pending_close is
skipped.

USAGE
  python3 exit_manager.py \
      --positions-json '[{...}, ...]' \
      [--pairs-json '[{...}, ...]'] \
      --now-utc 2026-09-07T18:05:00Z \
      [--session-close-utc 2026-09-07T20:00:00Z]

Each position dict:
  position_id, symbol, strike, expiration, option_type ('call'|'put'),
  quantity (int, currently OPEN contracts), entry_price (float),
  opened_at_utc (ISO), current_bid, current_ask, current_mark (floats),
  has_resting_stop (bool)   -- a resting stop-market SELL exists for this option
  has_resting_tp   (bool)   -- a resting limit SELL exists for this option
  has_pending_close(bool)   -- any other working SELL on this option
  tp1_filled       (bool)   -- a partial close SELL has already filled (=> runner)
  optional: thesis_broken (bool), underlying_consolidating (bool)

Prints a ticket per proposed close, then "PROPOSED_EXITS: <n>".
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '/home/claude/smc_bot')
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
try:
    from trade_log import append_event
except Exception:
    def append_event(*a, **k):  # best-effort only; nothing persists anyway
        return None

try:
    from live_risk_checks import HARD_STOP_PCT, TAKE_PROFIT_PCT, TAKE_PROFIT_FRACTION
except Exception:  # keep in sync with live_risk_checks.py
    HARD_STOP_PCT, TAKE_PROFIT_PCT, TAKE_PROFIT_FRACTION = 0.10, 0.30, 0.5

DEAD_TRADE_MIN = 90         # minutes in trade before the "capital idle" stop can fire
DEAD_TRADE_BAND = 0.08      # ...and only while |mark/entry - 1| is within this
EOD_FLATTEN_MIN = 15        # minutes before the session close to force every position flat

Z_EXIT_TARGET = 0.10        # pairs: |z| at/under this -> mean reversion done
Z_EXIT_ABANDON = 3.5        # pairs: |z| at/over this -> spread ran away, abandon

_RULE_PRIORITY = {
    "STOP_UNPROTECTED": 1, "EOD_FLATTEN": 2, "THESIS_BREAK": 3, "CONSOLIDATION": 4,
    "TAKE_PROFIT_1": 5, "RUNNER_GIVEBACK": 6, "DEAD_TRADE": 7,
    "PAIRS_TARGET": 2, "PAIRS_ABANDON": 2, "PAIRS_EOD": 2,
}


def _parse(ts):
    if ts is None:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _minutes_between(a, b):
    return (a - b).total_seconds() / 60.0


def _at_eod(now, session_close):
    return session_close is not None and now >= session_close - timedelta(minutes=EOD_FLATTEN_MIN)


def _evaluate_one(pos, now, session_close):
    """First matching rule -> (rule, close_qty, reason, extra), else None. Stateless."""
    entry = float(pos["entry_price"])
    mark = float(pos["current_mark"])
    qty = int(pos["quantity"])
    ret = mark / entry - 1.0 if entry else 0.0
    opened = _parse(pos.get("opened_at_utc"))
    mins_in = _minutes_between(now, opened) if opened else 0.0
    tp1_filled = bool(pos.get("tp1_filled"))

    if pos.get("has_pending_close"):
        return None  # a close is already working for this position

    # 1. hard stop -- only as a SAFETY NET when the resting stop is missing
    if mark <= entry * (1 - HARD_STOP_PCT) and not pos.get("has_resting_stop"):
        return ("STOP_UNPROTECTED", qty,
                f"mark ${mark:.2f} <= entry ${entry:.2f} - {HARD_STOP_PCT:.0%} and NO RESTING STOP -- "
                f"close now and place resting stops on the rest", {})

    # 2. end-of-day flatten
    if _at_eod(now, session_close):
        return "EOD_FLATTEN", qty, f"within {EOD_FLATTEN_MIN} min of the close, still open", {}

    # 3. thesis break
    if pos.get("thesis_broken"):
        return "THESIS_BREAK", qty, "orchestrator flagged the entry signal as invalidated", {}

    # 4. consolidation
    if pos.get("underlying_consolidating"):
        return "CONSOLIDATION", qty, "underlying went flat (3x 10-min candles inside +/-0.25%)", {}

    # 5. take-profit 1 -- only when the resting TP limit is missing
    if (not tp1_filled and not pos.get("has_resting_tp")
            and mark >= entry * (1 + TAKE_PROFIT_PCT)):
        tp_qty = qty // 2 if qty >= 2 else qty
        runner = qty - tp_qty
        return ("TAKE_PROFIT_1", tp_qty,
                f"mark ${mark:.2f} >= entry ${entry:.2f} + {TAKE_PROFIT_PCT:.0%}, no resting take-profit",
                {"runner_qty": runner, "move_stop_to_breakeven": runner > 0})

    # 6. runner give-back -- stateless: the post-TP1 remainder has round-tripped to breakeven
    if tp1_filled and mark <= entry:
        return ("RUNNER_GIVEBACK", qty,
                f"runner: mark ${mark:.2f} back at/under entry ${entry:.2f} after taking the first profit", {})

    # 7. dead-trade time stop
    if not tp1_filled and mins_in >= DEAD_TRADE_MIN and abs(ret) <= DEAD_TRADE_BAND:
        return ("DEAD_TRADE", qty,
                f"{mins_in:.0f} min in trade, P&L {ret:+.1%} within +/-{DEAD_TRADE_BAND:.0%} -- capital idle", {})

    return None


def evaluate_exits(positions, now_utc, session_close_utc=None):
    """Pure, stateless. Returns a list of close-proposal dicts."""
    now = _parse(now_utc)
    session_close = _parse(session_close_utc)
    proposals = []
    for pos in positions:
        match = _evaluate_one(pos, now, session_close)
        if not match:
            continue
        rule, close_qty, reason, extra = match
        prop = {
            "exit_id": str(uuid.uuid4()),
            "position_id": pos["position_id"],
            "symbol": pos["symbol"],
            "strike": pos["strike"],
            "expiration": pos["expiration"],
            "option_type": pos["option_type"],
            "rule": rule,
            "priority": _RULE_PRIORITY[rule],
            "reason": reason,
            "close_quantity": close_qty,
            "position_quantity": int(pos["quantity"]),
            "order_type": "market",
            "side": "sell",
            "position_effect": "close",
            "current_bid": pos.get("current_bid"),
            "current_ask": pos.get("current_ask"),
            "current_mark": pos.get("current_mark"),
            "entry_price": pos["entry_price"],
            "proposed_at_utc": now_utc,
        }
        if extra.get("move_stop_to_breakeven"):
            prop["also"] = (f"move the stop on the remaining {extra['runner_qty']} "
                            f"contract(s) up to breakeven (${float(pos['entry_price']):.2f})")
        proposals.append(prop)
    return proposals


def evaluate_pairs_exits(pairs, now_utc, session_close_utc=None):
    now = _parse(now_utc)
    session_close = _parse(session_close_utc)
    out = []
    for pk in pairs:
        if pk.get("has_pending_close"):
            continue
        z = abs(float(pk["current_z"]))
        rule = reason = None
        if z <= Z_EXIT_TARGET:
            rule, reason = "PAIRS_TARGET", f"|z| {z:.2f} <= {Z_EXIT_TARGET} -- mean reversion complete"
        elif z >= Z_EXIT_ABANDON:
            rule, reason = "PAIRS_ABANDON", f"|z| {z:.2f} >= {Z_EXIT_ABANDON} -- spread ran away, abandon"
        elif _at_eod(now, session_close):
            rule, reason = "PAIRS_EOD", f"within {EOD_FLATTEN_MIN} min of the close, package still open"
        if not rule:
            continue
        out.append({
            "exit_id": str(uuid.uuid4()),
            "position_id": f"pair:{pk['pair']}",
            "pair": pk["pair"],
            "rule": rule,
            "priority": _RULE_PRIORITY[rule],
            "reason": reason,
            "current_z": round(float(pk["current_z"]), 2),
            "legs": [pk.get("leg_a"), pk.get("leg_b")],
            "leg_a_option_id": pk.get("leg_a_option_id"),
            "leg_b_option_id": pk.get("leg_b_option_id"),
            "order_type": "market",
            "side": "sell",
            "position_effect": "close",
            "proposed_at_utc": now_utc,
        })
    return out


def _print_ticket(p):
    if "pair" in p:
        print(f"\nCLOSE PAIR {p['pair']}  [{p['rule']}]  {p['reason']}")
        for leg in p.get("legs") or []:
            if leg:
                print(f"  SELL to close {leg.get('quantity', 1)}x {leg.get('symbol')} "
                      f"${leg.get('strike')} {leg.get('option_type')}  (market)")
        print(f"  exit id {p['exit_id']}")
        return
    print(f"\nCLOSE {p['symbol']} ${p['strike']} {p['option_type']} exp {p['expiration']}  [{p['rule']}]")
    print(f"  {p['reason']}")
    print(f"  SELL to close: {p['close_quantity']}x of {p['position_quantity']} held  (market order)")
    print(f"  mark ${p['current_mark']:.2f}  (bid ${p['current_bid']:.2f} / ask ${p['current_ask']:.2f})  "
          f"vs entry ${float(p['entry_price']):.2f}")
    if p.get("also"):
        print(f"  then: {p['also']}")
    print(f"  exit id {p['exit_id']}  --  reply with the exit id to confirm and place it")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions-json", default="[]")
    ap.add_argument("--positions-file")
    ap.add_argument("--pairs-json", default="[]")
    ap.add_argument("--pairs-file")
    ap.add_argument("--now-utc", required=True)
    ap.add_argument("--session-close-utc")
    args = ap.parse_args()

    def _load(inline, path, default):
        if path:
            try:
                return json.load(open(path))
            except (FileNotFoundError, json.JSONDecodeError):
                return default
        return json.loads(inline)

    positions = _load(args.positions_json, args.positions_file, [])
    pairs = _load(args.pairs_json, args.pairs_file, [])

    proposals = evaluate_exits(positions, args.now_utc, args.session_close_utc)
    proposals += evaluate_pairs_exits(pairs, args.now_utc, args.session_close_utc)
    proposals.sort(key=lambda p: p["priority"])

    for p in proposals:
        append_event("exit_proposed", exit_id=p["exit_id"], position_id=p["position_id"],
                     rule=p["rule"], reason=p["reason"])
        _print_ticket(p)

    print(f"\nPROPOSED_EXITS: {len(proposals)}")
    if not proposals:
        print("(nothing to close this cycle)")
    print("\nNOTHING IS PLACED. Reply with an exit id to confirm and close it, "
          "or place the close yourself in the Robinhood app.")


if __name__ == "__main__":
    main()
