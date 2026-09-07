"""
exit_manager.py -- the live exit tier (2026-09-07, per explicit user request;
see docs/EXIT_SPEC.md section 5). PR 5 of the intraday rebuild.

WHAT IT IS. A pure-Python evaluator, same discipline as live_prepare_order.py:
NO broker/order tools are called or reachable from here. The orchestrating
scheduled session fetches open positions + live quotes (and, for the
thesis-break / consolidation rules, the underlying's recent candles) via the
MCP tools and passes the numbers in. This module decides which positions
should be closed and writes a **close proposal** to pending_exits.json for the
human to confirm. It never places a closing order.

WHEN IT RUNS. Its own scheduled task, every 5 minutes during market hours.

RULES (per position, first match wins -- priority order):
  1. HARD_STOP        mark <= entry * (1 - HARD_STOP_PCT)          -> close 100%
  2. EOD_FLATTEN      within EOD_FLATTEN_MIN of the session close   -> close 100%
  3. THESIS_BREAK     orchestrator flagged thesis_broken=true       -> close 100%
  4. CONSOLIDATION    orchestrator flagged underlying_consolidating -> close 100%
  5. TAKE_PROFIT_1    mark >= entry * (1 + TAKE_PROFIT_PCT)         -> close 50%
                                                                      (whole 1-lot),
                                                                      move to runner phase
  6. RUNNER_TRAIL     runner phase, mark <= peak_since_tp1 * (1 - RUNNER_TRAIL_PCT)
                                                                   -> close remainder
  7. DEAD_TRADE       >= DEAD_TRADE_MIN in trade and |mark/entry - 1| <= DEAD_TRADE_BAND
                                                                   -> close 100%

Protective "close 100%" rules (1-4) rank ABOVE the partial take-profit on
purpose: if there is a reason to be fully out, take it rather than only
trimming.

PAIRS (evaluate_pairs_exits): the package is managed on the spread z-score,
not a premium stop. |z| <= Z_EXIT_TARGET -> target hit, close both legs;
|z| >= Z_EXIT_ABANDON -> abandon, close both legs; plus the EOD flatten.

STATE. exit_state.json tracks per position: phase (pre_tp1 / runner), the
peak premium seen since TP1, and timestamps. pending_exits.json is the queue
of close proposals awaiting confirmation; a stale one (older than
EXIT_STALE_MINUTES) is expired at the start of each run, exactly like
live_expire_stale_orders.py does for entry proposals. A position that already
has an awaiting_confirmation proposal is not re-proposed unless a
higher-priority rule now fires (then the old proposal is superseded).

USAGE
  python3 exit_manager.py \
      --positions-json '[{...}, ...]' \
      [--pairs-json '[{...}, ...]'] \
      --now-utc 2026-09-07T18:05:00Z \
      [--session-close-utc 2026-09-07T20:00:00Z]

Each position dict needs:
  position_id, symbol, strike, expiration, option_type ('call'|'put'),
  quantity (int), entry_price (float, per-contract premium),
  opened_at_utc (ISO), current_bid, current_ask, current_mark (floats),
  has_resting_stop (bool),
  optional: thesis_broken (bool), underlying_consolidating (bool)

Prints, per proposed close, a ready-to-place ticket, then
  "PROPOSED_EXITS: <n>"  (0 is a normal, quiet result)
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '/home/claude/smc_bot')
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from trade_log import append_event

try:
    from live_risk_checks import HARD_STOP_PCT, TAKE_PROFIT_PCT, TAKE_PROFIT_FRACTION
except Exception:  # standalone / test fallback -- keep in sync with live_risk_checks.py
    HARD_STOP_PCT, TAKE_PROFIT_PCT, TAKE_PROFIT_FRACTION = 0.10, 0.30, 0.5

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
PENDING_EXITS_PATH = os.path.join(BACKTEST_DIR, "pending_exits.json")
EXIT_STATE_PATH = os.path.join(BACKTEST_DIR, "exit_state.json")

RUNNER_TRAIL_PCT = 0.20     # after TP1: close the runner if premium falls this far off its peak
DEAD_TRADE_MIN = 90         # minutes in trade before the "capital isn't working" stop can fire
DEAD_TRADE_BAND = 0.08      # ...and only while |mark/entry - 1| is within this
EOD_FLATTEN_MIN = 15        # minutes before the session close to force every position flat
EXIT_STALE_MINUTES = 45     # an unconfirmed close proposal older than this is expired

Z_EXIT_TARGET = 0.10        # pairs: |z| at/under this -> mean reversion done, close the package
Z_EXIT_ABANDON = 3.5        # pairs: |z| at/over this -> spread ran away, abandon the package

# Rule priority -- lower number wins when several match the same position.
_RULE_PRIORITY = {
    "HARD_STOP": 1, "EOD_FLATTEN": 2, "THESIS_BREAK": 3, "CONSOLIDATION": 4,
    "TAKE_PROFIT_1": 5, "RUNNER_TRAIL": 6, "DEAD_TRADE": 7,
    "PAIRS_TARGET": 2, "PAIRS_ABANDON": 2, "PAIRS_EOD": 2,
}


def _parse(ts):
    if ts is None:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _minutes_between(a, b):
    return (a - b).total_seconds() / 60.0


def _at_eod(now, session_close):
    """True once we're within EOD_FLATTEN_MIN minutes of the session close."""
    return session_close is not None and now >= session_close - timedelta(minutes=EOD_FLATTEN_MIN)


def expire_stale_proposals(pending, now, stale_minutes=EXIT_STALE_MINUTES):
    """Mark unconfirmed close proposals older than stale_minutes as expired.
    Returns (pending, n_expired)."""
    n = 0
    for p in pending:
        if p.get("status") != "awaiting_confirmation":
            continue
        age = _minutes_between(now, _parse(p["proposed_at_utc"]))
        if age > stale_minutes:
            p["status"] = "expired"
            p["expired_reason"] = f"unconfirmed for {age:.0f} min (limit {stale_minutes})"
            n += 1
            append_event("exit_expired", exit_id=p.get("exit_id"),
                         position_id=p.get("position_id"), rule=p.get("rule"),
                         age_minutes=round(age, 1))
    return pending, n


def _active_proposal_for(pending, position_id):
    for p in pending:
        if p.get("position_id") == position_id and p.get("status") == "awaiting_confirmation":
            return p
    return None


def _evaluate_one(pos, now, session_close, st):
    """Returns (rule, close_qty, reason, extra) for the first matching rule, or None.
    st is this position's mutable state dict (phase / peak_since_tp1)."""
    entry = float(pos["entry_price"])
    mark = float(pos["current_mark"])
    qty = int(pos["quantity"])
    ret = mark / entry - 1.0 if entry else 0.0
    opened = _parse(pos["opened_at_utc"])
    mins_in = _minutes_between(now, opened) if opened else 0.0
    phase = st.get("phase", "pre_tp1")

    # 1. hard stop
    if mark <= entry * (1 - HARD_STOP_PCT):
        note = "" if pos.get("has_resting_stop") else " -- NO RESTING STOP FOUND, place this now"
        return "HARD_STOP", qty, f"mark ${mark:.2f} <= entry ${entry:.2f} - {HARD_STOP_PCT:.0%}{note}", {}

    # 2. end-of-day flatten
    if _at_eod(now, session_close):
        return "EOD_FLATTEN", qty, f"within {EOD_FLATTEN_MIN} min of the session close, still open", {}

    # 3. thesis break
    if pos.get("thesis_broken"):
        return "THESIS_BREAK", qty, "orchestrator flagged the entry signal as invalidated", {}

    # 4. consolidation
    if pos.get("underlying_consolidating"):
        return "CONSOLIDATION", qty, "underlying went flat (3x 10-min candles inside +/-0.25%)", {}

    # 5. take-profit 1 (only once, pre-runner)
    if phase == "pre_tp1" and mark >= entry * (1 + TAKE_PROFIT_PCT):
        tp_qty = qty // 2 if qty >= 2 else qty
        runner = qty - tp_qty
        return ("TAKE_PROFIT_1", tp_qty,
                f"mark ${mark:.2f} >= entry ${entry:.2f} + {TAKE_PROFIT_PCT:.0%}",
                {"new_phase": "runner" if runner > 0 else "pre_tp1",
                 "peak_since_tp1": mark, "runner_qty": runner,
                 "move_stop_to_breakeven": runner > 0})

    # 6. runner trailing stop
    if phase == "runner":
        peak = max(float(st.get("peak_since_tp1", mark)), mark)
        st["peak_since_tp1"] = peak  # keep the peak current even when not exiting
        if mark <= peak * (1 - RUNNER_TRAIL_PCT):
            return ("RUNNER_TRAIL", qty,
                    f"runner: mark ${mark:.2f} fell {RUNNER_TRAIL_PCT:.0%} off its ${peak:.2f} peak", {})

    # 7. dead-trade time stop
    if phase == "pre_tp1" and mins_in >= DEAD_TRADE_MIN and abs(ret) <= DEAD_TRADE_BAND:
        return ("DEAD_TRADE", qty,
                f"{mins_in:.0f} min in trade, P&L {ret:+.1%} within +/-{DEAD_TRADE_BAND:.0%} -- capital idle", {})

    return None


def evaluate_exits(positions, now_utc, session_close_utc=None,
                    state=None, pending=None):
    """Pure evaluation. Returns (proposals, new_state, superseded).
    proposals: list of close-proposal dicts (not yet written).
    superseded: exit_ids of prior awaiting_confirmation proposals a
    higher-priority rule now overrides.
    """
    now = _parse(now_utc)
    session_close = _parse(session_close_utc)
    state = dict(state or {})
    pending = pending or []

    proposals, superseded = [], []
    live_ids = set()

    for pos in positions:
        pid = pos["position_id"]
        live_ids.add(pid)
        st = dict(state.get(pid, {}))
        st.setdefault("phase", "pre_tp1")

        match = _evaluate_one(pos, now, session_close, st)

        # persist peak/phase updates from evaluation even when no exit fires
        state[pid] = {**st, "last_seen_utc": now_utc}

        if not match:
            continue
        rule, close_qty, reason, extra = match

        existing = _active_proposal_for(pending, pid)
        if existing:
            if _RULE_PRIORITY[rule] >= _RULE_PRIORITY.get(existing.get("rule"), 99):
                continue  # already have an equal-or-higher-priority proposal pending
            existing["status"] = "superseded"
            existing["superseded_by_rule"] = rule
            superseded.append(existing.get("exit_id"))

        prop = {
            "exit_id": str(uuid.uuid4()),
            "position_id": pid,
            "symbol": pos["symbol"],
            "strike": pos["strike"],
            "expiration": pos["expiration"],
            "option_type": pos["option_type"],
            "rule": rule,
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
            "status": "awaiting_confirmation",
        }
        if extra.get("move_stop_to_breakeven"):
            prop["also"] = (f"move the stop on the remaining {extra['runner_qty']} "
                            f"contract(s) up to breakeven (${float(pos['entry_price']):.2f})")
        proposals.append(prop)

        if rule == "TAKE_PROFIT_1":
            state[pid]["phase"] = extra["new_phase"]
            state[pid]["peak_since_tp1"] = extra["peak_since_tp1"]
            state[pid]["tp1_proposed_at"] = now_utc
        else:
            state[pid]["phase"] = "close_proposed"

    # prune state for positions that are no longer open
    for pid in list(state.keys()):
        if pid not in live_ids:
            state.pop(pid, None)

    return proposals, state, superseded


def evaluate_pairs_exits(pairs, now_utc, session_close_utc=None, pending=None):
    """pairs: [{pair, leg_a_option_id, leg_b_option_id, current_z, opened_at_utc,
    leg_a:{symbol,strike,option_type,quantity,current_mark}, leg_b:{...}}].
    Returns a list of package-close proposals."""
    now = _parse(now_utc)
    session_close = _parse(session_close_utc)
    pending = pending or []
    out = []
    for pk in pairs:
        key = f"pair:{pk['pair']}"
        if _active_proposal_for(pending, key):
            continue
        z = abs(float(pk["current_z"]))
        rule = None
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
            "position_id": key,
            "pair": pk["pair"],
            "rule": rule,
            "reason": reason,
            "current_z": round(float(pk["current_z"]), 2),
            "legs": [pk.get("leg_a"), pk.get("leg_b")],
            "leg_a_option_id": pk.get("leg_a_option_id"),
            "leg_b_option_id": pk.get("leg_b_option_id"),
            "order_type": "market",
            "side": "sell",
            "position_effect": "close",
            "proposed_at_utc": now_utc,
            "status": "awaiting_confirmation",
        })
    return out


def _print_ticket(p):
    if "pair" in p:
        print(f"\nCLOSE PAIR {p['pair']}  [{p['rule']}]  {p['reason']}")
        for leg in p.get("legs") or []:
            if not leg:
                continue
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

    positions = _load_json(args.positions_file, None) if args.positions_file \
        else json.loads(args.positions_json)
    pairs = _load_json(args.pairs_file, None) if args.pairs_file \
        else json.loads(args.pairs_json)

    now = _parse(args.now_utc)
    pending = _load_json(PENDING_EXITS_PATH, [])
    state = _load_json(EXIT_STATE_PATH, {})

    pending, n_expired = expire_stale_proposals(pending, now)

    proposals, state, superseded = evaluate_exits(
        positions, args.now_utc, args.session_close_utc, state=state, pending=pending)
    pair_proposals = evaluate_pairs_exits(
        pairs, args.now_utc, args.session_close_utc, pending=pending)

    all_new = proposals + pair_proposals
    pending.extend(all_new)
    with open(PENDING_EXITS_PATH, "w") as f:
        json.dump(pending, f, indent=2)
    with open(EXIT_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

    for p in all_new:
        append_event("exit_proposed", exit_id=p["exit_id"], position_id=p["position_id"],
                     rule=p["rule"], reason=p["reason"])
        _print_ticket(p)

    if n_expired:
        print(f"\n({n_expired} stale exit proposal(s) expired)")
    if superseded:
        print(f"({len(superseded)} prior proposal(s) superseded by a higher-priority rule)")
    print(f"\nPROPOSED_EXITS: {len(all_new)}")
    if not all_new:
        print("(nothing to close this cycle)")
    print("\nNOTHING IS PLACED. Reply with an exit id to confirm and close it, "
          "or place the close yourself in the Robinhood app.")


if __name__ == "__main__":
    main()
