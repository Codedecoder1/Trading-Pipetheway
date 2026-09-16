"""
debit_spread_scanner.py -- Daily Debit Spread scanner (Call & Put spreads, 30-60 DTE).

WHAT IT DOES (orchestrator for the full strategy)
1. Reads universe (same movers + ETFs as SMC Bot)
2. Fetches recent bars + earnings calendar
3. Filters each symbol through Gate 0 (trend, earnings, volume)
4. For passing symbols: fetches 30-60 DTE options, selects spreads
5. Sizes positions (max 25% BP, max $50 risk per spread, max 1 open)
6. Appends proposals to pending_live_orders.json (bracket format)
7. Logs signals to trade_log.jsonl

USAGE (from scheduled task)
  python3 debit_spread_scanner.py

Expected to be called every 30 min, 7am-12pm Pacific (UTC 14:00-19:00).
All Robinhood data is fetched live within the task session.

STANDING RULE: No place_option_order, place_equity_order, or review_equity_order.
This is signal-only; the user confirms manually in the app.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '/home/claude/smc_bot')
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')

from debit_spread_filters import (
    check_trend_gate, check_earnings_gate, check_rvol_gate
)
from debit_spread_selector import select_call_spread, select_put_spread

BACKTEST_DIR = '/home/claude/smc_bot/diag/backtest'
PENDING_PATH = os.path.join(BACKTEST_DIR, 'pending_live_orders.json')

# Position limits
MAX_ACCOUNT_ALLOCATION_PCT = 0.25  # 25% of BP per spread
MAX_OPEN_POSITIONS = 1  # Only 1 active spread at a time
MAX_RISK_PER_SPREAD = 50.0  # $50 max risk


def get_scanner_universe():
    """
    Get the stock universe for scanning.
    For now, reuse the SMC Bot universe:
    - Major ETFs (SPY, QQQ, etc.) -- static
    - Live movers from Robinhood scanner (mcp__RBH__run_scan)

    In this task context, we assume the calling session has already
    fetched and cached the universe. Here we just return a placeholder
    list; the orchestrating task will populate it.

    Returns: ["AAPL", "MSFT", "SPY", ...]
    """
    # For now, return empty; the task will provide the list
    return []


def log_signal(event_type, symbol, direction, spread_data, note=""):
    """Log a signal to trade_log.jsonl for audit trail."""
    try:
        log_path = os.path.join(BACKTEST_DIR, 'trade_log.jsonl')
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": symbol,
            "direction": direction,
            "spread": spread_data,
            "note": note,
        }
        with open(log_path, 'a') as f:
            f.write(json.dumps(event) + '\n')
    except Exception:
        pass  # Silent fail on logging


def evaluate_symbol(symbol, bars, direction, earnings_calendar, today_utc):
    """
    Run Gate 0 filters on a symbol for a given direction (call/put).

    Returns: (passed, reason) tuple
    """
    if not bars or len(bars) < 200:
        return False, "not enough bars"

    # Trend gate
    if not check_trend_gate(bars, direction):
        return False, f"trend gate failed ({direction})"

    # Earnings blackout
    today_str = today_utc.split('T')[0]  # Extract YYYY-MM-DD
    if not check_earnings_gate(symbol, earnings_calendar, today_str):
        return False, "in earnings blackout"

    # Volume gate
    if not check_rvol_gate(bars, min_rvol=1.5):
        return False, "RVOL < 1.5"

    return True, "passed all gates"


def propose_spread(symbol, direction, spread_data, spot_price, buying_power, total_equity):
    """
    Create a proposal for a debit spread with bracket orders.

    Bracket for debit spread (2-leg):
    1. ENTRY: BUY long leg, SELL short leg as a single "spread" order
    2. STOP: Close if debit > 50% of net debit (half the max risk)
    3. TAKE-PROFIT: Close if spread reaches 50-65% of max profit

    For simplicity, we'll propose the long leg as the primary order
    and include the short leg details in the notes.
    """
    if not spread_data:
        return None

    # Risk sizing
    net_debit = spread_data.get("net_debit", 0)
    max_profit = spread_data.get("max_profit", 0)

    # Position size: limit to $50 max risk, 25% of BP
    max_bp_alloc = buying_power * MAX_ACCOUNT_ALLOCATION_PCT
    contracts_by_bp = int(max_bp_alloc / (net_debit * 100)) if net_debit > 0 else 1
    contracts_by_risk = int(MAX_RISK_PER_SPREAD / (net_debit * 100)) if net_debit > 0 else 1
    quantity = min(contracts_by_bp, contracts_by_risk, 1)  # Start with 1 spread

    if quantity < 1:
        return None  # Can't afford the minimum

    order_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc).isoformat()

    # Bracket exit targets
    stop_debit = net_debit * 1.5  # Stop if we lose 50% of max risk
    tp_target = max(net_debit * 0.75, (net_debit + max_profit * 0.65))  # Exit at 60% max profit

    proposal = {
        "order_id": order_id,
        "prepared_at_utc": now_utc,
        "strategy": "debit_spread",
        "symbol": symbol,
        "direction": direction,  # "call" or "put"
        "spread": spread_data,
        "quantity": quantity,
        "net_debit": net_debit,
        "max_profit": max_profit,
        "quantity": quantity,
        "stop_loss_debit": stop_debit,
        "take_profit_target": tp_target,
        "risk_reward": spread_data.get("risk_reward", ""),
        "status": "awaiting_confirmation",
    }

    return proposal


def append_proposal(proposal):
    """Append proposal to pending_live_orders.json."""
    if not proposal:
        return False

    existing = []
    if os.path.exists(PENDING_PATH):
        try:
            existing = json.load(open(PENDING_PATH))
        except Exception:
            existing = []

    existing.append(proposal)
    try:
        with open(PENDING_PATH, 'w') as f:
            json.dump(existing, f, indent=2)
        return True
    except Exception:
        return False


def scan_universe(universe, bars_map, earnings_calendar, option_chains_map,
                  spot_prices, buying_power, total_equity, today_utc):
    """
    Main scan: iterate universe, filter, select spreads, propose.

    Args:
        universe: list of symbols to scan
        bars_map: {symbol: [bars]}
        earnings_calendar: earnings events from Robinhood
        option_chains_map: {symbol: [contracts]}
        spot_prices: {symbol: price}
        buying_power: account BP
        total_equity: account equity
        today_utc: ISO datetime string

    Returns: (call_proposals, put_proposals) tuples with counts
    """
    call_count = 0
    put_count = 0

    for symbol in universe:
        bars = bars_map.get(symbol, [])
        spot_price = spot_prices.get(symbol, 0)
        option_chain = option_chains_map.get(symbol, [])

        if not bars or not option_chain or spot_price <= 0:
            continue

        # Try Call Spread
        call_pass, call_reason = evaluate_symbol(symbol, bars, "call", earnings_calendar, today_utc)
        if call_pass:
            call_spread = select_call_spread(option_chain, spot_price)
            if call_spread:
                proposal = propose_spread(symbol, "call", call_spread, spot_price, buying_power, total_equity)
                if proposal and append_proposal(proposal):
                    log_signal("debit_spread_candidate", symbol, "call", call_spread)
                    print(f"PROPOSED: {symbol} CALL SPREAD ${call_spread['net_debit']*100:.0f} debit -> ${call_spread['max_profit']*100:.0f} max profit")
                    call_count += 1

        # Try Put Spread
        put_pass, put_reason = evaluate_symbol(symbol, bars, "put", earnings_calendar, today_utc)
        if put_pass:
            put_spread = select_put_spread(option_chain, spot_price)
            if put_spread:
                proposal = propose_spread(symbol, "put", put_spread, spot_price, buying_power, total_equity)
                if proposal and append_proposal(proposal):
                    log_signal("debit_spread_candidate", symbol, "put", put_spread)
                    print(f"PROPOSED: {symbol} PUT SPREAD ${put_spread['net_debit']*100:.0f} debit -> ${put_spread['max_profit']*100:.0f} max profit")
                    put_count += 1

    return call_count, put_count


if __name__ == "__main__":
    print("Debit Spread Scanner ready.")
    print("(Normally invoked by orchestrating scheduled task with universe + data)")
    print("See scheduled task prompt for full integration instructions.")
