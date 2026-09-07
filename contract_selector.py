"""
Contract-selection policy for the live pipeline, REVISION 1 (2026-08-27)
+ REVISION 2 (2026-08-28), per explicit user request.

WHY THIS EXISTS: the pipeline's long-standing convention (see
live_prepare_order.py's original docstring) was "always trade the
nearest expiration's ATM contract." The $150-account Monday-Wednesday
what-if simulation (2026-08-26) showed that convention is structurally
incompatible with the live risk gate's $140 max-premium cap on any
underlying priced much above ~$100: an ATM call on GLW (~$145 stock)
already cost $445 total, DELL (~$450 stock) cost $1,248, TGT (~$163
stock) cost $256 -- all rejected on affordability before an order was
ever prepared, even though the underlying signals were valid. Zero of
those three would-be trades could execute.

This module is a pure function, no tool access -- same pattern as
live_risk_checks.py and live_prepare_order.py. The calling (live)
session fetches the nearest expiration's full contract chain itself
(get_option_chains / get_option_instruments / get_option_quotes) and
passes the resulting list in; this function picks which one to trade.

Selection policy:
  1. Try the ATM contract first (closest |delta| to 0.50). If its
     ask_price * 100 fits under max_premium, use it -- unchanged
     behavior for any stock cheap enough that ATM already fits (this is
     most of the existing universe; REVISION 1 only changes what happens
     when it DOESN'T fit).
  2. If ATM doesn't fit, look at every contract with |delta| in
     delta_band (0.25-0.35 by default) that DOES fit under max_premium,
     and pick whichever of those is closest to target_delta (0.30).
     OTM contracts cost less than ATM for the same underlying move
     because they carry less intrinsic value, which is exactly why this
     step can bring a $450 stock's contract under a $140 cap where ATM
     couldn't.
  3. If nothing in the band fits either, reject -- affordability is
     still the final word. live_risk_checks.check_affordability
     re-validates whatever this function returns anyway, at execution
     time, right before an order is prepared; this function's job is
     giving that check a better candidate to evaluate, not replacing it.

Trade-off being made explicitly here (worth knowing, not hiding): a
0.25-0.35 delta OTM contract has a lower probability of finishing
in-the-money than an ATM (~0.50 delta) contract, and moves less per
dollar the underlying moves (lower gamma exposure near entry). This
policy accepts that trade-off ONLY when ATM is unaffordable in the
first place -- the alternative isn't "ATM at a better price," it's "no
trade at all" under Update 3 (Accept Universe Filtering) users
considered and explicitly asked to move away from. If affordability
turns out to reject the fallback too often in practice, consider
Update 2 (cap the scanner universe by stock price, e.g. under $60-70)
as a complementary fix -- this module doesn't touch the scanner
universe, only what happens after a signal on a pricier name already
fired.

REVISION 2 (2026-08-28): max_premium is no longer a fixed $140 constant
duplicated from live_risk_checks.py -- it's now computed live from the
account's actual buying power via live_risk_checks.get_max_contract_budget()
(buying_power * 0.85), imported directly rather than kept "in sync" by
hand. Pass buying_power (the live number from get_portfolio) and this
module derives the budget itself; MAX_PREMIUM_PER_CONTRACT below remains
only as the fallback for a caller that doesn't have a live buying_power
figure (e.g. this module's own smoke test).

REVISION 3 (2026-08-30): optional vix passthrough. When the calling
session has a live VIX reading (see live_risk_checks.py's REVISION 2
docstring), pass it here too so contract selection is checked against the
SAME regime-adjusted budget the final risk gate will use -- otherwise
this function could pick an ATM/OTM contract sized for a normal-vol
budget that the high-vol-adjusted run_all_checks() then rejects anyway.
Only takes effect when max_premium isn't given explicitly and
buying_power is; omitted (as any pre-REVISION-3 caller does), behavior
is unchanged.

REVISION 4 (2026-08-31), per explicit user request -- small-account
survival overhaul. At the account's current ~$170 size, ATM contracts on
anything but the cheapest underlyings are unaffordable outright (a real
example: GRMN ATM cost $500+ against a budget under $150), and even the
REVISION 1 OTM fallback (0.25-0.35 delta) doesn't go far enough OTM to
reliably fit a ~$42 budget on a $40+ stock. New rule: when the underlying
looks pricier than SMALL_ACCOUNT_PRICE_THRESHOLD ($40), skip the "try ATM
first" step entirely and go straight to a tighter, further-OTM delta band
(HIGH_PRICE_DELTA_BAND, 0.20-0.25 instead of 0.25-0.35) -- a contract
further from the money costs less per contract, which is exactly what a
capital-constrained account needs, at the cost of a lower probability of
finishing in-the-money and less gamma exposure near entry (same
trade-off REVISION 1 already accepted, just leaned into further).

This function isn't handed the underlying's live stock price directly
(only the option contracts list) -- rather than plumb a new parameter
through resolve_contract.py's CLI and every trigger prompt that calls it,
this reuses the ATM contract's own strike as a proxy (an ATM strike is,
by construction, close to spot). Good enough for a threshold check; if
more precision is ever needed here, add a real --underlying-price
parameter instead of tightening this proxy further.

REVISION 5 (2026-08-31), per explicit user request: SMALL_ACCOUNT_PRICE_THRESHOLD
lowered from $40 to $15. Same forced-OTM mechanism as REVISION 4 above --
only the trigger price moved. Practical effect: the forced-OTM (skip ATM
entirely, go straight to the tighter 0.20-0.25 delta band) path now kicks
in for almost every underlying in this pipeline's usual universe (SMC's
scan floor alone is $10, so nearly everything it surfaces now clears
$15), not just the pricier names. ATM is still tried first, and can still
be picked, for anything $15 and under.

REVISION 6 (2026-09-06), per explicit user request: SMALL_ACCOUNT_PRICE_THRESHOLD
raised from $15 to $1000 -- i.e. the forced-OTM path is now effectively
disabled for this pipeline's whole universe. Paired with live_risk_checks.py
REVISION 7 (budget back to 85% of buying power): with a ~$143 budget the
ATM contract fits for most names the scans surface, so "try ATM first"
(higher delta, higher probability of finishing in-the-money, more gamma
near entry) becomes the default again. The 0.25-0.35 delta OTM step
(DELTA_BAND) still runs as the affordability fallback for any underlying
whose ATM does not fit the budget -- it just is not force-selected
anymore, and the tighter 0.20-0.25 HIGH_PRICE_DELTA_BAND is now
unreachable in practice. Raise/lower this constant if you want the
forced-OTM behavior back for pricier names.
"""
import sys
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from live_risk_checks import get_max_contract_budget, MAX_PREMIUM_PER_CONTRACT

TARGET_DELTA = 0.30
DELTA_BAND = (0.25, 0.35)

# REVISION 4 (forced-OTM path for pricier underlyings), REVISION 5 ($40 -> $15),
# REVISION 6 ($15 -> $1000, i.e. forced-OTM effectively disabled -- ATM-first default).
SMALL_ACCOUNT_PRICE_THRESHOLD = 1000.0
HIGH_PRICE_DELTA_BAND = (0.20, 0.25)
HIGH_PRICE_TARGET_DELTA = 0.225


def _contract_cost(contract):
    return contract["ask"] * 100


def select_contract(contracts, direction, max_premium=None, buying_power=None,
                     vix=None, target_delta=TARGET_DELTA, delta_band=DELTA_BAND):
    """
    contracts: list of dicts, one per available strike at the (already
    chosen) nearest expiration. Each dict needs at least:
      strike (float), ask (float), bid (float), delta (float),
      option_id (str)
    delta sign convention: Robinhood reports calls with positive delta
    and puts with negative delta. This function normalizes to abs(delta)
    internally so direction doesn't have to be handled twice by the
    caller; pass contracts with their real (signed) delta as-is.
    direction: 'call' or 'put' -- informational/for the returned method
    string only, since abs(delta) already makes the band symmetric.
    max_premium: explicit override, if you want to skip the dynamic
      calculation entirely (e.g. testing). Takes priority over buying_power.
    buying_power: REVISION 2 (2026-08-28) -- the account's current live
      buying power. When max_premium isn't given explicitly, the budget is
      derived from this via get_max_contract_budget() (85% of buying
      power). If neither is given, falls back to the static
      MAX_PREMIUM_PER_CONTRACT constant.
    vix: REVISION 3 (2026-08-30) -- optional live VIX reading, forwarded
      to get_max_contract_budget() so the budget used here matches the
      regime-adjusted budget run_all_checks() will use downstream. No
      effect if max_premium is given explicitly.

    Returns (contract, method, note):
      contract: the selected dict from `contracts` (same object, not a
        copy), or None if nothing affordable was found.
      method: "ATM" | "OTM_DELTA" | "REJECTED_NO_AFFORDABLE_CONTRACT"
      note: human-readable reasoning, safe to log or put in a
        notification.
    """
    if max_premium is None:
        max_premium = get_max_contract_budget(buying_power, vix=vix) if buying_power is not None else MAX_PREMIUM_PER_CONTRACT

    if not contracts:
        return None, "REJECTED_NO_AFFORDABLE_CONTRACT", "no contracts supplied"

    for c in contracts:
        if "delta" not in c or c["delta"] is None:
            return None, "REJECTED_NO_AFFORDABLE_CONTRACT", \
                f"contract at strike {c.get('strike')} missing delta -- cannot evaluate selection policy"

    atm = min(contracts, key=lambda c: abs(abs(c["delta"]) - 0.50))
    atm_cost = _contract_cost(atm)
    underlying_price_proxy = atm["strike"]  # REVISION 4: ATM strike stands in for spot price

    forced_otm = underlying_price_proxy > SMALL_ACCOUNT_PRICE_THRESHOLD
    if forced_otm:
        lo, hi = HIGH_PRICE_DELTA_BAND
        target = HIGH_PRICE_TARGET_DELTA
    else:
        lo, hi = delta_band
        target = target_delta
        if atm_cost <= max_premium:
            return atm, "ATM", (f"ATM contract (strike {atm['strike']}, delta {atm['delta']:.3f}) "
                                 f"costs ${atm_cost:.2f}, fits under ${max_premium:.2f} cap")

    candidates = [c for c in contracts
                  if lo <= abs(c["delta"]) <= hi and _contract_cost(c) <= max_premium]
    if candidates:
        pick = min(candidates, key=lambda c: abs(abs(c["delta"]) - target))
        pick_cost = _contract_cost(pick)
        if forced_otm:
            return pick, "OTM_DELTA", (
                f"underlying priced ~${underlying_price_proxy:.2f} (> ${SMALL_ACCOUNT_PRICE_THRESHOLD:.2f} "
                f"small-account threshold) -- skipped ATM (would cost ${atm_cost:.2f}), went straight to "
                f"{lo:.2f}-{hi:.2f} delta OTM contract (strike {pick['strike']}, delta {pick['delta']:.3f}), "
                f"costs ${pick_cost:.2f}, fits under ${max_premium:.2f} cap"
            )
        return pick, "OTM_DELTA", (
            f"ATM contract (strike {atm['strike']}, delta {atm['delta']:.3f}) cost ${atm_cost:.2f}, "
            f"exceeded ${max_premium:.2f} cap -- stepped down to {lo:.2f}-{hi:.2f} "
            f"delta OTM contract (strike {pick['strike']}, delta {pick['delta']:.3f}), "
            f"costs ${pick_cost:.2f}, fits under cap"
        )

    if forced_otm:
        return None, "REJECTED_NO_AFFORDABLE_CONTRACT", (
            f"underlying priced ~${underlying_price_proxy:.2f} (> ${SMALL_ACCOUNT_PRICE_THRESHOLD:.2f} "
            f"small-account threshold), ATM would cost ${atm_cost:.2f} -- and no contract with delta in "
            f"[{lo:.2f}, {hi:.2f}] fit under ${max_premium:.2f} cap either -- no trade"
        )
    return None, "REJECTED_NO_AFFORDABLE_CONTRACT", (
        f"ATM contract (strike {atm['strike']}, delta {atm['delta']:.3f}) cost ${atm_cost:.2f}, "
        f"exceeded ${max_premium:.2f} cap, and no contract with delta in "
        f"[{lo:.2f}, {hi:.2f}] fit under the cap either -- no trade"
    )


if __name__ == "__main__":
    # smoke test, using the ATM prices from the 2026-08-26 $150-account
    # simulation (GLW/DELL/TGT) plus synthetic OTM contracts at plausible
    # deltas/prices to exercise the fallback path.
    glw_chain = [
        {"strike": 145.0, "ask": 4.45, "bid": 4.35, "delta": 0.50, "option_id": "glw-atm"},
        {"strike": 150.0, "ask": 2.10, "bid": 2.00, "delta": 0.31, "option_id": "glw-otm-1"},
        {"strike": 152.5, "ask": 1.35, "bid": 1.25, "delta": 0.22, "option_id": "glw-otm-2"},
    ]
    dell_chain = [
        {"strike": 450.0, "ask": 12.48, "bid": 12.20, "delta": 0.50, "option_id": "dell-atm"},
        {"strike": 470.0, "ask": 5.80, "bid": 5.60, "delta": 0.32, "option_id": "dell-otm-1"},
        {"strike": 480.0, "ask": 3.90, "bid": 3.70, "delta": 0.24, "option_id": "dell-otm-2"},
    ]
    tgt_chain = [
        {"strike": 162.5, "ask": 2.56, "bid": 2.46, "delta": 0.50, "option_id": "tgt-atm"},
        {"strike": 165.0, "ask": 1.30, "bid": 1.20, "delta": 0.30, "option_id": "tgt-otm-1"},
    ]

    for name, chain in [("GLW", glw_chain), ("DELL", dell_chain), ("TGT", tgt_chain)]:
        contract, method, note = select_contract(chain, "call")
        print(f"{name}: method={method}")
        print(f"  {note}")
        if contract:
            print(f"  -> selected strike {contract['strike']}, ask ${contract['ask']:.2f} "
                  f"(${contract['ask']*100:.2f} total), option_id={contract['option_id']}")
        print()

    # REVISION 2: same TGT chain, but via the dynamic buying_power path
    # instead of the static $140 fallback -- at $177 buying power the
    # budget is $150.45, comfortably wide enough for the ATM contract
    # ($256 total) to still fail and fall through to the OTM step.
    print("--- dynamic path: TGT @ $177 buying power ---")
    contract, method, note = select_contract(tgt_chain, "call", buying_power=177.0)
    print(f"TGT: method={method}")
    print(f"  {note}")
