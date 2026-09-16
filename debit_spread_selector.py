"""
debit_spread_selector.py -- Strike & spread selection for Call/Put Debit Spreads.

WHAT IT DOES
Given an expiration's contract chain, selects Call and Put spreads that meet:
1. Delta targets (ATM long ~0.50, OTM short ~0.35-0.40)
2. Spread width ($1.00 or $2.50 depending on price level)
3. Liquidity gates (bid-ask <= 10%, OI >= 500, min contract price >= $0.15)
4. Net debit cap (max 50% of spread width)

Input: option chain, direction (call/put), stock price
Output: {"long_strike", "long_delta", "long_price", "short_strike", "short_delta",
         "short_price", "net_debit", "spread_width", "long_oid", "short_oid"} or None

USAGE (from orchestrator):
  from debit_spread_selector import select_call_spread, select_put_spread

  call_spread = select_call_spread(option_chain, spot_price)
  put_spread = select_put_spread(option_chain, spot_price)
"""

TARGET_LONG_DELTA = 0.50
TARGET_SHORT_DELTA_CALL = 0.35
TARGET_SHORT_DELTA_PUT = -0.35
MAX_BID_ASK_SPREAD_PCT = 0.10
MIN_OPEN_INTEREST = 500
MIN_CONTRACT_PRICE = 0.15
MAX_NET_DEBIT_PCT = 0.50


def get_spread_width(spot_price):
    """
    Spread width logic:
    - Stocks >= $100: use $2.50 spread
    - Stocks < $100: use $1.00 spread
    """
    return 2.50 if spot_price >= 100 else 1.00


def check_liquidity(contract):
    """
    Check if a single contract meets liquidity gates:
    - Bid-ask <= 10%
    - Open interest >= 500
    - Mid-price >= $0.15
    """
    bid = contract.get("bid_price", 0)
    ask = contract.get("ask_price", 0)
    oi = contract.get("open_interest", 0)
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0

    if mid < MIN_CONTRACT_PRICE:
        return False, "price too low"

    if oi < MIN_OPEN_INTEREST:
        return False, "OI too low"

    if bid <= 0 or ask <= 0:
        return False, "no bid/ask"

    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    if spread_pct > MAX_BID_ASK_SPREAD_PCT:
        return False, "bid-ask > 10%"

    return True, "OK"


def find_closest_delta(contracts, target_delta, leg_type="long"):
    """
    Find the contract closest to target_delta.
    leg_type: "long" or "short" (for call/put interpretation).
    """
    valid = []
    for c in contracts:
        delta = c.get("delta", 0)
        ok, _ = check_liquidity(c)
        if ok and delta is not None:
            valid.append((abs(delta - target_delta), c))

    if not valid:
        return None
    valid.sort()
    return valid[0][1]


def select_call_spread(option_chain, spot_price):
    """
    Select a Call Debit Spread:
    - Long: ATM call at ~0.50 delta
    - Short: OTM call at ~0.35-0.40 delta, $1.00 (or $2.50) above long strike

    Returns dict with spread details, or None if no valid spread found.
    """
    if not option_chain:
        return None

    spread_width = get_spread_width(spot_price)

    # Find long leg (ATM, ~0.50 delta call)
    long_contract = find_closest_delta(option_chain, TARGET_LONG_DELTA, "long")
    if not long_contract:
        return None

    long_strike = long_contract.get("strike_price")
    long_delta = long_contract.get("delta")
    long_bid = long_contract.get("bid_price", 0)
    long_ask = long_contract.get("ask_price", 0)
    long_oid = long_contract.get("id")

    if not long_oid:
        return None

    # Find short leg (OTM, ~0.35-0.40 delta call, spread_width above long)
    short_target_strike = long_strike + spread_width
    short_contracts = [
        c for c in option_chain
        if abs(c.get("strike_price", 0) - short_target_strike) < 0.01
    ]

    if not short_contracts:
        return None

    short_contract = find_closest_delta(short_contracts, TARGET_SHORT_DELTA_CALL, "short")
    if not short_contract:
        return None

    short_strike = short_contract.get("strike_price")
    short_delta = short_contract.get("delta")
    short_bid = short_contract.get("bid_price", 0)
    short_ask = short_contract.get("ask_price", 0)
    short_oid = short_contract.get("id")

    if not short_oid:
        return None

    # Compute net debit: we pay for the long, receive for the short
    long_price = long_ask  # We BUY at ask
    short_price = short_bid  # We SELL at bid
    net_debit = long_price - short_price

    if net_debit < 0:
        net_debit = 0  # Shouldn't happen for debit spread, but safeguard

    max_debit = spread_width * MAX_NET_DEBIT_PCT
    if net_debit > max_debit:
        return None  # Debit too high

    return {
        "direction": "call",
        "long_strike": long_strike,
        "long_delta": long_delta,
        "long_bid": long_bid,
        "long_ask": long_ask,
        "long_oid": long_oid,
        "short_strike": short_strike,
        "short_delta": short_delta,
        "short_bid": short_bid,
        "short_ask": short_ask,
        "short_oid": short_oid,
        "net_debit": net_debit,
        "max_profit": spread_width - net_debit,
        "spread_width": spread_width,
        "risk_reward": f"Risk ${net_debit*100:.0f}, Max Profit ${(spread_width-net_debit)*100:.0f}",
    }


def select_put_spread(option_chain, spot_price):
    """
    Select a Put Debit Spread:
    - Long: ATM put at ~-0.50 delta
    - Short: OTM put at ~-0.35-0.40 delta, $1.00 (or $2.50) below long strike

    Returns dict with spread details, or None if no valid spread found.
    """
    if not option_chain:
        return None

    spread_width = get_spread_width(spot_price)

    # Find long leg (ATM, ~-0.50 delta put)
    long_contract = find_closest_delta(option_chain, -TARGET_LONG_DELTA, "long")
    if not long_contract:
        return None

    long_strike = long_contract.get("strike_price")
    long_delta = long_contract.get("delta")
    long_bid = long_contract.get("bid_price", 0)
    long_ask = long_contract.get("ask_price", 0)
    long_oid = long_contract.get("id")

    if not long_oid:
        return None

    # Find short leg (OTM, ~-0.35-0.40 delta put, spread_width below long)
    short_target_strike = long_strike - spread_width
    short_contracts = [
        c for c in option_chain
        if abs(c.get("strike_price", 0) - short_target_strike) < 0.01
    ]

    if not short_contracts:
        return None

    short_contract = find_closest_delta(short_contracts, -TARGET_SHORT_DELTA_PUT, "short")
    if not short_contract:
        return None

    short_strike = short_contract.get("strike_price")
    short_delta = short_contract.get("delta")
    short_bid = short_contract.get("bid_price", 0)
    short_ask = short_contract.get("ask_price", 0)
    short_oid = short_contract.get("id")

    if not short_oid:
        return None

    # Compute net debit
    long_price = long_ask  # We BUY at ask
    short_price = short_bid  # We SELL at bid
    net_debit = long_price - short_price

    if net_debit < 0:
        net_debit = 0

    max_debit = spread_width * MAX_NET_DEBIT_PCT
    if net_debit > max_debit:
        return None

    return {
        "direction": "put",
        "long_strike": long_strike,
        "long_delta": long_delta,
        "long_bid": long_bid,
        "long_ask": long_ask,
        "long_oid": long_oid,
        "short_strike": short_strike,
        "short_delta": short_delta,
        "short_bid": short_bid,
        "short_ask": short_ask,
        "short_oid": short_oid,
        "net_debit": net_debit,
        "max_profit": spread_width - net_debit,
        "spread_width": spread_width,
        "risk_reward": f"Risk ${net_debit*100:.0f}, Max Profit ${(spread_width-net_debit)*100:.0f}",
    }
