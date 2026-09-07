"""
Pure risk-check functions for the live (real-money) notify-and-confirm
pipeline. No network/tool calls in here -- the calling session fetches
live quotes/positions/P&L itself (via the MCP tools) and passes the
resulting numbers in. Keeping these as plain functions makes them easy to
verify in isolation before they gate a real order.

Static fallback parameters (set 2026-08-26 -- raised from the original
$100/-$15 after the backtest showed 9 of 10 P&L-validated ATM setups were
unaffordable at the $100 cap). These remain the defaults for any caller
that doesn't supply live account numbers (standalone tests, this module's
own smoke test below):
  MAX_PREMIUM_PER_CONTRACT = $140.00 (total cost = ask * 100 shares)
  MAX_SPREAD_PCT           = 10% of ask
  MAX_OPEN_POSITIONS       = 1
  DAILY_DRAWDOWN_CAP       = -$21.00 (= -15% of $140, realized + unrealized, today only)
  HARD_STOP_PCT            = 0.15 (matches backtested exit engine)

REVISION 1 (2026-08-28), per explicit user request: the premium cap and
drawdown cap are no longer fixed dollar amounts -- they now scale with the
account's actual live numbers via get_max_contract_budget() /
get_max_daily_drawdown() below. As the account grows (or shrinks), the
budget and drawdown ceiling move with it instead of staying pinned to the
$140/$150-account snapshot they were set from. run_all_checks() computes
the dynamic values itself when the caller passes buying_power/total_equity
(the live pipeline always will); it falls back to the static constants
above when they're omitted, so this stays backward compatible with any
caller that only wants to test contract-level checks in isolation.

Note this is intentionally uncapped both directions: there's no ceiling
that stops the per-contract budget from growing indefinitely as the
account grows, and no floor that stops it from shrinking as the account
drops. Worth revisiting if the account moves far from its current size.

REVISION 2 (2026-08-30), per explicit user request -- VIX-based market
regime sizing, shared by BOTH live strategies (SMC and the Wednesday
VWAP/DMI screener) since this lives in the one risk module they both
import. Originally proposed via yfinance (`yf.Ticker("^VIX")`); the VIX
is available directly through Robinhood's own index tools instead --
mcp__RBH__get_index_quotes with instrument_id
"3b912aa2-88f9-4682-8ae3-e39520bdf4db" (resolved via
mcp__RBH__search(asset_type="market_index", query="VIX"), confirmed
working 2026-08-30, live quote returned $14.43) -- so no external data
source was needed here at all, unlike the earlier Wikipedia/yfinance
proposals. get_market_regime() classifies the current VIX reading;
get_max_contract_budget() applies the resulting size_multiplier when a
vix value is passed in (optional -- omitting it, as any pre-REVISION-2
caller does, leaves the budget calculation exactly as before). The
threshold (25.0) and the "cut position sizing under high VIX" behavior
are exactly as the user specified; REGIME_HIGH_VOL_SIZE_MULTIPLIER is the
one new tunable, kept as a module constant rather than a further-nested
magic number so it's easy to find and adjust later. This only touches
premium budget (position sizing) -- the daily drawdown cap is untouched,
since the user's own script only described "reduce position sizing."

REVISION 4 (2026-08-31), per explicit user request -- small-account
survival overhaul. With the live account down to ~$170, the REVISION 1
85%-of-buying-power budget was still sizing single-leg trades at $140+,
which is 82-100% of total capital on one trade -- a live example that
day (GRMN put) rejected on affordability because ATM alone cost $500+
with nothing in the OTM band fitting under even the old $140 cap either.
Two changes:
  1. get_max_contract_budget()'s multiplier drops from 0.85 to 0.25 (25%
     of buying power per trade, not 85%) -- this is a POSITION-SIZING
     cap, deliberately proportional so it keeps scaling sensibly if the
     account grows, rather than staying pinned to today's ~$42 snapshot.
     MAX_PREMIUM_PER_CONTRACT (the static fallback for callers without a
     live buying_power figure) is updated to match at today's account
     size: 170 * 0.25 = $42.50.
  2. New MIN_PREMIUM_TOTAL floor ($15.00, check_premium_floor() below):
     rejects contracts priced so low they're likely low-probability
     "lottery tickets" rather than a real directional bet. This one is
     intentionally a FIXED dollar floor, not a percentage of the
     account -- it reflects something about option pricing/probability
     (how cheap is "too cheap to be a real edge"), not about how big the
     account is, so unlike the budget cap it does not scale with
     buying_power.
  The user's spec also described a separate fixed "$0.42 ceiling" gate;
  that's intentionally NOT implemented as a second, independent
  constant here -- it would just be a second number that has to be kept
  in sync with the 25%-of-buying-power budget above (they're the same
  ~$42.50 today only because the account happens to be ~$170; a fixed
  $42 ceiling would silently stop making sense the moment the account
  moves). check_affordability() below already enforces this as the
  ceiling, and it moves correctly with the account automatically.

REVISION 5 (2026-08-31), per explicit user request -- MAX_OPEN_POSITIONS
raised from 1 to 5. Rationale given: contract prices vary widely ($20
lottery-ticket-floor contracts up through hundreds/thousands for
higher-priced underlyings), and the account is meant to grow, so pinning
the whole system to a single open position at a time under-uses cheap,
well-sized trades. This constant is the only thing that changes --
check_position_cap() below already took a live open_position_count and
compared it to a cap, so the 5 flows through automatically to
run_all_checks() / pairs_prepare_order.py / live_prepare_order.py with no
other code changes needed. Two things worth knowing about how this
actually plays out, both by design rather than oversight:
  1. Each strategy's hourly notify-and-confirm loop still proposes at
     most ONE new signal per firing, and the live trigger prompts still
     skip preparing a new proposal while a prior one is sitting
     unconfirmed in pending_live_orders.json. So positions still
     accumulate one at a time, never as a burst of simultaneous
     confirmation requests -- raising the cap changes how many positions
     can be open TOGETHER over the course of a trading day/week, not how
     many get proposed in one cycle.
  2. get_max_contract_budget() sizes every trade off *current* buying
     power (25% of whatever's left), so each successive position gets a
     smaller budget than the last as cash gets committed -- e.g. roughly
     $38 -> $28 -> $21 -> $16 -> ~$12 on today's ~$152 buying power,
     and that last figure is already under the $15 premium floor. In
     practice, on today's account size, the 5-open-positions ceiling is
     unlikely to bind before the budget/floor math does -- it becomes
     more reachable as the account grows (starting with the $150 pending
     deposit), which is the intended behavior: the cap scales with
     opportunity as the account does, rather than being an arbitrary
     wall.

REVISION 6 (2026-09-02), per explicit user request -- get_max_contract_budget()'s
multiplier raised from 0.25 to 0.40 (40% of buying power per trade, not
25%). Trigger: a live PSKY put signal rejected as
REJECTED_NO_AFFORDABLE_CONTRACT -- ATM cost $50.00 against that day's
$45.66 cap (25% of ~$182.64 buying power), and the strike ladder had
nothing in the 0.25-0.35 delta OTM band either (jumped straight from a
too-far-OTM $10.50 strike to the $11.00 ATM strike). The user asked to
raise the cap; this keeps the dynamic percentage-of-buying-power design
from REVISION 4 (still scales with the account, still no fixed dollar
number to go stale) rather than reverting to a fixed cap, but accepts a
materially larger fraction of a still-small account risked on one trade
as a deliberate, explicit tradeoff -- worth revisiting if the account
balance changes a lot in either direction. MAX_PREMIUM_PER_CONTRACT (the
static fallback for callers without a live buying_power figure) is
updated to match at today's account size: 182.64 * 0.40 = ~$73.06.

REVISION 7 (2026-09-06), per explicit user request -- get_max_contract_budget()'s
multiplier raised from 0.40 to 0.85 (85% of buying power per trade). This
is the same value REVISION 1 originally used, before the REVISION 4/5/6
small-account walk-down. The user reviews and triple-checks every proposal
by hand before approving it and explicitly accepts the concentrated risk:
at ~$168 buying power this sizes one contract at up to ~$143, so in
practice one open position at a time on the current account. Still a
percentage of live buying power (scales with the account, no fixed dollar
number to go stale). MAX_PREMIUM_PER_CONTRACT (the static fallback for
callers without a live buying_power figure) updated to match at today's
account size: 168.12 * 0.85 = ~$142.90.
"""

MAX_PREMIUM_PER_CONTRACT = 142.90
MIN_PREMIUM_TOTAL = 15.00
MAX_SPREAD_PCT = 0.10
MAX_OPEN_POSITIONS = 5
DAILY_DRAWDOWN_CAP = -21.00
HARD_STOP_PCT = 0.15

VIX_HIGH_VOL_THRESHOLD = 25.0
REGIME_HIGH_VOL_SIZE_MULTIPLIER = 0.5  # halve the contract budget when VIX > threshold


def get_market_regime(vix: float) -> dict:
    """Classifies the current VIX reading into a market regime and the
    position-sizing multiplier that regime implies. Pure function -- the
    calling session fetches the live VIX value itself (get_index_quotes)
    and passes it in here."""
    if vix > VIX_HIGH_VOL_THRESHOLD:
        return {
            "regime": "HIGH_VOLATILITY_FEAR",
            "vix": vix,
            "size_multiplier": REGIME_HIGH_VOL_SIZE_MULTIPLIER,
            "note": f"VIX {vix:.2f} > {VIX_HIGH_VOL_THRESHOLD:.1f} -- high volatility/fear regime, "
                    f"position sizing cut to {REGIME_HIGH_VOL_SIZE_MULTIPLIER:.0%} of normal",
        }
    return {
        "regime": "STABLE_NORMAL",
        "vix": vix,
        "size_multiplier": 1.0,
        "note": f"VIX {vix:.2f} <= {VIX_HIGH_VOL_THRESHOLD:.1f} -- stable/normal volatility regime, "
                f"full position sizing",
    }


# Dynamic Sizing Functions
def get_max_contract_budget(buying_power: float, vix: float = None) -> float:
    budget = buying_power * 0.85  # REVISION 7: caps any one trade at 85% of buying power (was 40%)
    if vix is not None:
        budget *= get_market_regime(vix)["size_multiplier"]
    return budget

def get_max_daily_drawdown(total_equity: float) -> float:
    return total_equity * 0.15  # 15% risk cap per session


def check_affordability(ask_price, max_premium=MAX_PREMIUM_PER_CONTRACT):
    """ask_price is per-contract (per-share) premium; total cost = ask_price * 100.
    This also serves as the "ceiling" gate from the small-account playbook --
    see REVISION 4 docstring above for why there isn't a second, separate
    fixed-dollar ceiling constant."""
    total_cost = ask_price * 100
    ok = total_cost <= max_premium
    note = (f"contract cost ${total_cost:.2f} ({'<=' if ok else '>'} ${max_premium:.2f} budget)")
    return ok, note, total_cost


def check_premium_floor(ask_price, min_premium=MIN_PREMIUM_TOTAL):
    """REVISION 4 (2026-08-31): rejects contracts priced so low they're more
    likely a low-probability "lottery ticket" than a real directional bet.
    Fixed dollar floor -- deliberately does NOT scale with buying_power (see
    REVISION 4 docstring)."""
    total_cost = ask_price * 100
    ok = total_cost >= min_premium
    note = f"contract cost ${total_cost:.2f} ({'>=' if ok else '<'} ${min_premium:.2f} floor)"
    return ok, note


def check_spread(bid_price, ask_price, max_spread_pct=MAX_SPREAD_PCT):
    if ask_price <= 0:
        return False, "ask price is zero or negative -- cannot evaluate spread"
    spread_pct = (ask_price - bid_price) / ask_price
    ok = spread_pct <= max_spread_pct
    note = f"spread {spread_pct:.1%} ({'<=' if ok else '>'} {max_spread_pct:.0%} of ask)"
    return ok, note


def check_position_cap(open_position_count, cap=MAX_OPEN_POSITIONS):
    ok = open_position_count < cap
    note = f"{open_position_count} open position(s) ({'<' if ok else '>='} cap of {cap})"
    return ok, note


def check_daily_drawdown(today_pnl_dollars, cap=DAILY_DRAWDOWN_CAP):
    """today_pnl_dollars: realized + unrealized P&L for today, in dollars (negative = loss)."""
    ok = today_pnl_dollars > cap
    note = f"today's P&L ${today_pnl_dollars:+.2f} ({'above' if ok else 'at/below'} ${cap:.2f} cap)"
    return ok, note


def compute_hard_stop_price(ask_price, hard_stop_pct=HARD_STOP_PCT):
    """Sell-to-close stop_market trigger price, rounded to the cent."""
    return round(ask_price * (1 - hard_stop_pct), 2)


def run_all_checks(ask_price, bid_price, open_position_count, today_pnl_dollars,
                    buying_power=None, total_equity=None, vix=None):
    """Returns (all_pass: bool, results: dict) -- runs every gate, does not short-circuit,
    so a rejected order's notification can explain every reason it was rejected.

    REVISION 1 (2026-08-28): buying_power/total_equity are optional. When the
    caller supplies them (the live pipeline always does -- see
    live_prepare_order.py), the affordability and drawdown thresholds are
    computed live via get_max_contract_budget()/get_max_daily_drawdown()
    instead of using the static MAX_PREMIUM_PER_CONTRACT/DAILY_DRAWDOWN_CAP
    constants. Whichever thresholds were actually used are echoed back in
    results['sizing'] so the notification/log shows the real numbers a
    proposal was checked against, not just a fixed assumption.

    REVISION 2 (2026-08-30): vix is optional. When supplied along with
    buying_power, get_max_contract_budget() applies the VIX-regime size
    multiplier and the resulting regime classification is echoed back in
    results['regime'] (None when vix isn't supplied, so old callers/logs
    see an explicit absence rather than a missing key)."""
    max_premium = get_max_contract_budget(buying_power, vix=vix) if buying_power is not None else MAX_PREMIUM_PER_CONTRACT
    drawdown_cap = -get_max_daily_drawdown(total_equity) if total_equity is not None else DAILY_DRAWDOWN_CAP
    regime = get_market_regime(vix) if vix is not None else None

    afford_ok, afford_note, total_cost = check_affordability(ask_price, max_premium=max_premium)
    floor_ok, floor_note = check_premium_floor(ask_price)
    spread_ok, spread_note = check_spread(bid_price, ask_price)
    pos_ok, pos_note = check_position_cap(open_position_count)
    dd_ok, dd_note = check_daily_drawdown(today_pnl_dollars, cap=drawdown_cap)
    results = {
        "affordability": {"ok": afford_ok, "note": afford_note, "total_cost": round(total_cost, 2)},
        "premium_floor": {"ok": floor_ok, "note": floor_note},
        "spread": {"ok": spread_ok, "note": spread_note},
        "position_cap": {"ok": pos_ok, "note": pos_note},
        "daily_drawdown": {"ok": dd_ok, "note": dd_note},
        "sizing": {
            "max_premium": round(max_premium, 2),
            "min_premium": MIN_PREMIUM_TOTAL,
            "drawdown_cap": round(drawdown_cap, 2),
            "buying_power": buying_power,
            "total_equity": total_equity,
            "dynamic": buying_power is not None and total_equity is not None,
        },
        "regime": regime,
    }
    all_pass = afford_ok and floor_ok and spread_ok and pos_ok and dd_ok
    return all_pass, results


if __name__ == "__main__":
    # smoke test
    ok, results = run_all_checks(ask_price=0.85, bid_price=0.80, open_position_count=0, today_pnl_dollars=0.0)
    print("all_pass:", ok)
    for k, v in results.items():
        print(" ", k, v)
    print("hard stop price @ $0.85 ask:", compute_hard_stop_price(0.85))

    ok2, results2 = run_all_checks(ask_price=2.50, bid_price=2.00, open_position_count=1, today_pnl_dollars=-16.0)
    print("\nall_pass (should be False, multiple fails):", ok2)
    for k, v in results2.items():
        print(" ", k, v)

    # REVISION 1 dynamic-sizing smoke test, using the account's current
    # live numbers (~$177 buying power/equity as of 2026-08-28).
    print("\n--- dynamic sizing @ $177 buying power / $177 equity ---")
    print("max contract budget:", get_max_contract_budget(177.0))
    print("max daily drawdown :", get_max_daily_drawdown(177.0))
    ok3, results3 = run_all_checks(ask_price=1.45, bid_price=1.38, open_position_count=0,
                                    today_pnl_dollars=0.0, buying_power=177.0, total_equity=177.0)
    print("all_pass:", ok3)
    for k, v in results3.items():
        print(" ", k, v)

    # REVISION 2 VIX-regime smoke test -- same $177 account, two VIX readings.
    print("\n--- VIX regime @ $177 buying power ---")
    print("stable  (VIX 14.43):", get_market_regime(14.43))
    print("fear    (VIX 31.20):", get_market_regime(31.20))
    print("budget, VIX=14.43 (stable, no cut):", get_max_contract_budget(177.0, vix=14.43))
    print("budget, VIX=31.20 (fear, halved)  :", get_max_contract_budget(177.0, vix=31.20))
    ok4, results4 = run_all_checks(ask_price=1.45, bid_price=1.38, open_position_count=0,
                                    today_pnl_dollars=0.0, buying_power=177.0, total_equity=177.0,
                                    vix=31.20)
    print("all_pass (high-vix, tighter budget):", ok4)
    for k, v in results4.items():
        print(" ", k, v)
