"""
Optional STRICTER contract-quality filter layer, on top of the existing
SMC confluence signal (structure + candlestick). This module does NOT
replace the entry signal -- it's a second gate you can apply to a signal
that has already fired, to decide whether the specific option contract is
"high enough quality" to actually trade live.

=====================================================================
VERSION LABEL: "the best one yet"  (2026-08-25, revision 3)
=====================================================================
Revision 1 (same day) implemented three approved changes -- time-of-day-
relative RVOL, PEG-as-advisory, and %-of-price scaling for theta/gamma/
vega/ATR -- then spent five rounds live-tuning six numeric constants
against that same day's 6 signals until 2 of them passed. That was
correctly called out as curve-fitting: tuning a gate live against the
one dataset it's about to be judged on tells you where the knobs
happened to land, not whether the strategy has an edge. Every one of
those constants got reverted or replaced in revision 2.

Revision 2 restructured the gate into two independent layers instead of
one flat AND of nine checks, and reset the numeric thresholds to
principled values instead of live-tuned ones. Revision 3 fixed a metric
mismatch discovered immediately after: Layer 1's ATR check was being fed
5-minute-bar ATR (bar-to-bar chop over ~70 minutes), which runs at a
totally different scale than the %-of-price floor it was being compared
against (was implicitly calibrated for daily range) -- so it rejected
literally every signal that day regardless of RVOL or VWAP. Worse, 5-min
ATR actively penalizes a stock that consolidated tightly right before a
real breakout -- exactly the setup this bot is meant to catch. Revision 3
swaps in DAILY ATR(period=14) and locks Layer 1's three checks (not to be
loosened live against any single day's data again):

  LAYER 1 -- MARKET QUALITY (binary, non-negotiable, evaluated first,
  LOCKED as of 2026-08-25 pending a real multi-week backtest).
  Answers "is this stock actually moving, with volume, in the signaled
  direction, right now" -- properties of the underlying/signal, not of
  any specific contract. If Layer 1 fails, evaluation STOPS immediately
  -- Layer 2 is not even computed, because no contract on a stock that
  isn't genuinely moving is worth buying.
    - RVOL (time-of-day-relative): >= 1.0x
    - Daily ATR(14) as %-of-price ("does this stock move enough per day
      to justify buying options on it"): >= 2.0%. MUST be daily ATR, not
      5-min-bar ATR -- see check_atr_pct()'s docstring.
    - VWAP alignment: price must be on the correct side for the
      signaled direction. This is NOT a tunable numeric threshold --
      it's a binary confirmation that price hasn't already moved
      against the trade. Loosening this doesn't recalibrate a bias,
      it removes a real risk control, so it isn't exposed as a
      *_MIN / *_MAX constant the way the others are.

  LAYER 2 -- CONTRACT SELECTION (only runs if Layer 1 passed).
  Answers "given a genuinely-moving, volume-confirmed, price-confirmed
  stock, which specific contract is a decent one to buy":
    - Delta: 0.35 to 0.55 (calls) | -0.55 to -0.35 (puts) -- standard
      liquidity band, reset from the live-tuned [0.25, 0.55]
    - Theta: >= -8% of premium/day (back to the original 1:1 scaling,
      not the -35% we tuned down to)
    - Gamma: scaled band around [0.05, 0.15] at $100 reference price
      (unchanged -- this one was never tuned)
    - Vega: <= 10% of premium, abs (unchanged -- never tuned)
    - Spread: <= $0.05 OR <= 10% of mark (back from the tuned 30%)
    - PEG: advisory only (see change #2 below) -- computed and reported
      at whichever layer the contract reaches, never gates either one.

This split fixes a real problem revision 1 had: loosening Delta to admit
deeper-ITM contracts pushed absolute spreads and premiums up, which then
forced Spread% and Theta% to loosen too just to avoid instantly
rejecting the wider contracts Delta had just let in. That's parameter
interdependence compounding across a single flat AND -- separating
"is the stock tradeable" from "which contract on it" breaks the cascade,
because a stock that fails Layer 1 never reaches Layer 2's Delta/Theta/
Spread checks in the first place, and Layer 2's checks stay at their
principled values instead of being dragged around by Layer 1 failures.

Original three changes (still in effect, now organized into the layers
above):
  1. RVOL is TIME-OF-DAY-RELATIVE instead of full-day-vs-full-month:
     volume-so-far as of the signal's timestamp, compared against the
     same fraction of the 30-day average volume through that time of
     day (elapsed regular-session minutes / 390, session = 13:30-20:00
     UTC) -- what a live scanning bot actually sees in real time.
  2. PEG-undefined is ADVISORY, not a hard fail -- loss-making/earnings-
     declining "story" stocks (this bot's typical mover profile) very
     often have no meaningful trailing-growth PEG; compute_peg_approx()
     still runs and reports, but never gates either layer.
  3. theta/gamma/vega/ATR are scaled as a PERCENTAGE of price/premium
     instead of fixed dollar amounts, so they don't systematically
     penalize expensive underlyings (LITE ~$860, DELL ~$450) or
     rubber-stamp cheap ones.

IMPORTANT CAVEATS (read before trusting this blindly):
  1. PEG here is NOT the standard analyst-forward-estimate PEG. Robinhood
     doesn't expose forward EPS growth estimates, so this is approximated
     as trailing PE / trailing YoY net-income growth %, using the same
     fiscal quarter one year prior. Unstable, distorted for companies
     off a low/negative earnings base, undefined when YoY growth is
     negative -- hence advisory-only.
  2. RVOL time-of-day-relative requires "volume so far as of the signal
     timestamp." Fed from a live 1-minute bar stream, the running total
     under-counts relative to the official end-of-day volume near the
     close, because market-on-close auction volume often isn't in the
     continuous print stream yet. For signals firing very close to
     20:00 UTC, treat the computed RVOL as a conservative lower bound.
  3. VWAP alignment should compare price to VWAP AT THE ENTRY BAR's
     timestamp, not end-of-day "latest" VWAP -- pass vwap_at_entry
     accordingly when wiring this into live signal checks.
  4. These reset numeric values are principled (faithful 1:1 dollar-to-
     percent translations, or standard textbook liquidity bands) but
     they are still UNVALIDATED against actual trade outcomes. The
     right way to finish calibrating this module is a multi-week
     backtest with known outcomes, not further live tuning against a
     single day's signals -- that's the mistake revision 1 made and
     revision 2 exists to undo.

=====================================================================
REVISION 4 (2026-08-26): empirical RVOL curve, from the Phase 1 backtest
=====================================================================
Ran the locked Layer 1 gate against the first real multi-week backtest
(narrowed 4-week scope: 2026-07-27 to 2026-08-24, the 61-symbol universe
minus the 8 chronic movers, 123 mover-day events, 51 raw confluence
signal hits). Result: 0/51 passed Layer 1 -- 48 of the 51 failures were
RVOL-driven (median rvol=0.36x against the 1.0x floor, not a near miss).

Root cause was NOT the 1.0x floor -- it was the "expected volume by now"
formula. check_rvol_relative assumed volume accrues LINEARLY across the
session (expected_by_now = avg_volume_30d * elapsed_minutes/390). Real
intraday volume is U-shaped: heavy at the open, quiet mid-session, heavy
at the close. Measuring the ACTUAL shape from the same 123-event/45-symbol
dataset (build_volume_curve.py) shows the linear assumption is wrong in
both directions -- e.g. by minute 65 real cumulative volume is typically
~30% of the day already (vs. 17% linear), but by minute 360 it's still
only ~83% of the day (vs. 92% linear); the last 30 minutes alone
typically carries ~17% of the entire day's volume. A stock genuinely
trading at "normal pace" for that time of day was being scored as if it
were 2-3x behind pace, because the yardstick was wrong, not the stock.

Fix: replaced the linear elapsed_fraction with EMPIRICAL_CUM_VOL_FRAC, a
78-point (one per 5-min bar from session open to close) cumulative-
volume-fraction curve measured directly from that same backtest dataset.
RVOL_MIN stays at 1.0x -- the floor itself was never the problem, the
"expected" side of the ratio was. This is exactly the "derive Layer 2 [and
now Layer 1's shape] objectively from the backtest rather than tuning live"
process the multi-week backtest was commissioned for -- see
diag/backtest/build_volume_curve.py for the derivation and
diag/backtest/phase1_layer1_eval.py for the before/after evaluation.

=====================================================================
REVISION 5 (2026-08-26): OR-gate volume confirmation (fixes the real bug)
=====================================================================
Chasing the still-0/51 result after Revision 4 found the actual root
cause: it's not the U-shape, and it's not that these movers lack real
volume -- it's a DATA-BASIS MISMATCH. avg_volume_30d is built from the
"day" interval's volume field. Checked directly against the SAME day's
regular-session intraday bars summed (5-min bars, bounds=regular) for
all 123 backtest events: the day-bar figure is ALWAYS higher, by 1.9x to
6.4x, median 2.65x -- consistent with the day bar reporting full
consolidated-tape volume while intraday bars report primary-exchange-
only volume. A live bot's volume_so_far can only ever be sourced from
the intraday feed, so it can structurally never reach a 1.0x (or even
0.75x, some days) ratio against a denominator computed on a ~2.65x
larger basis -- no amount of tuning RVOL_MIN fixes a unit mismatch.

Fix (specified directly): stop relying solely on a cross-feed ratio.
RVOL (still empirical-curve-corrected, floor lowered to 0.75x since the
denominator is now understood to run structurally high) is OR'd with a
same-feed, same-accounting-basis volume-spike check: does the signal's
own bar carry >= 2.0x the trailing 20-bar volume moving average, at
whatever interval (5/10/30min) the signal fired on. Both sides of that
second clause come from the identical intraday bar stream, so it has no
cross-feed mismatch to begin with -- it catches a bar-level participation
burst even on a day where the day-bar-based RVOL denominator is
systematically inflated.

    PASS if: (time_of_day_rvol >= 0.75x) OR (signal_bar_volume >= 2.0 *
    trailing_20_bar_volume_MA)

check_rvol_relative was folded into check_volume_confirmation, which
implements this OR-gate and is what evaluate_contract's Layer 1 now
calls. See diag/backtest/phase1_layer1_eval_v2.py for the re-run.

=====================================================================
REVISION 6 (2026-08-26): hard RVOL floor guardrail on the impulse clause
=====================================================================
Revision 5's OR-gate let the volume-spike clause pass a signal on its
own, with no floor at all on the cumulative RVOL side -- 8 of the 12
signals that passed v2 had RVOL as low as 0.23x-0.42x, i.e. a stock that
was nearly dead-quiet ALL SESSION until one bar spiked. A single bar
spike on top of a genuinely quiet day is a weaker signal than the same
spike on top of at least moderate session-long participation, and the
OR-gate as built couldn't tell those apart.

Fix (specified directly): add a hard floor -- the impulse clause can
only pass a signal if cumulative time-of-day RVOL is ALSO >= 0.50x.
RVOL >= 0.75x still passes on its own (no impulse needed). Net gate:

    PASS if: (time_of_day_rvol >= 0.75x)
             OR (time_of_day_rvol >= 0.50x AND signal_bar_volume >=
                 2.0 * trailing_20_bar_volume_MA)

RVOL_HARD_FLOOR = 0.50 added; check_volume_confirmation updated so the
spike clause is gated by it. See diag/backtest/phase1_layer1_eval_v3.py
for the re-run.

=====================================================================
REVISION 7 (2026-08-26): drop ATR and session RVOL from the Layer 1 GATE
=====================================================================
Two problems identified reviewing the whole pipeline together, both
confirmed by the v3 numbers (123 events -> 51 raw signals -> 4 pass):

  1. ATR_PCT_MIN was dead code. Every signal in this pipeline already
     cleared the upstream Stage A movers filter (>=3% daily move) before
     Layer 1 ever runs, and a stock that just moved 3%+ in a day will
     essentially always show >=2.0% daily ATR(14) -- confirmed: it
     passed 51/51 (100%) in the v3 run, filtering out precisely nothing.
     Keeping it in Layer 1 doesn't hurt, but it isn't doing any work
     either -- it's just the movers filter's own logic paraphrased.
  2. Session-cumulative RVOL is hobbled by a real data-source
     limitation, not a strategy flaw (see REVISION 5): building a true
     time-of-day historical volume baseline needs a proper
     minute-by-minute 30-day volume profile, which the connected
     Robinhood endpoint doesn't provide -- comparing session-cumulative
     volume against a day-bar-sourced 30-day average structurally
     undercounts and reads artificially low. Confirmed in v3: RVOL never
     independently cleared 0.75x anywhere in the dataset; every pass came
     through the bar-impulse clause. Tuning RVOL's threshold against that
     data measures the data limitation, not the stock.

Fix (specified directly): remove both from the Layer 1 GATE.
  - ATR is still computed and reported -- as ADVISORY (like PEG),
    informational only, never blocks either layer.
  - Session RVOL (_time_of_day_rvol / EMPIRICAL_CUM_VOL_FRAC /
    check_volume_confirmation) is left in the module, UNUSED by
    evaluate_contract, in case a real volume-profile data source
    (ThetaData / Polygon / etc.) gets integrated later and this becomes
    worth reviving -- but Layer 1 no longer calls it.
  - The bar-impulse half of REVISION 5/6 becomes Layer 1's ONLY volume
    check, standalone (no RVOL floor to gate it anymore): does the
    signal's own bar carry >= VOLUME_SPIKE_MULT (2.0x) the trailing
    VOLUME_SPIKE_LOOKBACK-bar (20-bar, i.e. the preceding ~100 minutes
    for 5-min bars) volume moving average. Runs natively off the same
    intraday bars this pipeline already has -- no historical baseline
    needed at all.

Cleaned-up Layer 1 gate (2 checks, down from 3):
    Movers filter (external, upstream)  >=3% daily move
      -> Volume Impulse:  signal_bar_volume >= 2.0 * trailing_20_bar_MA
      -> VWAP Alignment:  call needs close > vwap, put needs close < vwap

check_volume_impulse() implements the new standalone check.
check_atr_pct's result moved into `advisory`. See
diag/backtest/phase1_layer1_eval_v4.py for the re-run.

=====================================================================
REVISION 8 (2026-08-26): session-time cutoff added to Layer 1 GATE
=====================================================================
Surfaced by the Phase 2 Synthetic Underlying Replay backtest (10 setups,
30 contracts), not by numeric tuning: the 3 setups whose signal fired
after 19:30 UTC (AMZN 8/3 @ 19:55Z, NVDA 8/12 @ 19:50Z, SHW 7/27 @ 19:50Z)
left only 5-10 minutes of the regular session to actually replay the exit
plan. Several of their legs never got the chance to trigger the phase-1
trailing stop, the hard stop, OR TP1 before the exit engine ran out of
bars and had to mark the position STILL_OPEN at whatever the last print
happened to be -- in live trading that same shortfall means either an
unhedged short-dated option carried past the close or a forced
market-on-close exit that neither this bot nor its backtest accounts for.

Unlike every other change in this file's revision history, this is NOT a
numeric constant tuned against backtest outcomes -- it's a structural
scheduling fact (is there enough clock left in the session to run the
trade plan at all), so it doesn't need the "wait for a multi-week
backtest before touching Layer 1" caution the LOCKED-since-2026-08-25
note above was written for. It gates independently of volume_impulse and
vwap: a signal can have perfect volume/VWAP confirmation and still fail
here purely because there isn't enough session left to manage it.

Fix (specified directly): reject any signal whose timestamp is after
SESSION_TIME_CUTOFF (19:30:00 UTC, i.e. the last 30 minutes of the
13:30-20:00 UTC regular session). Exactly 19:30:00 itself stays eligible
-- it's the boundary, not past it. check_session_time() implements this;
evaluate_contract() now takes signal_timestamp and Layer 1 is
volume_impulse AND vwap AND session_time (3 checks, up from 2). See
diag/backtest/phase1_layer1_eval_v5.py and
diag/backtest/session_time_filter.py for the re-run and the standalone
post-hoc filter this was validated against first (identical result: 9 of
the 12 v4-passing signals stay eligible).

=====================================================================
REVISION 9 (2026-08-26): VOLUME_SPIKE_MULT and SESSION_TIME_CUTOFF
loosened by explicit user request (not backtest-driven)
=====================================================================
Unlike every prior numeric change in this file, this one is NOT the
result of a backtest or curve-fitting exercise -- it's a direct,
explicit instruction from the live-trading operator to loosen two of
the three Layer 1 gates:
  - VOLUME_SPIKE_MULT: 2.0x -> 1.4x (signal-bar volume now only needs to
    clear 1.4x the trailing 20-bar average instead of 2.0x -- a
    meaningfully looser bar, expected to pass more signals through).
  - SESSION_TIME_CUTOFF: 19:30:00 UTC -> 20:00:00 UTC (the regular-
    session close itself) -- this effectively DISABLES the REVISION 8
    session-time gate, since no signal can fire after the session has
    already closed. The exit-management risk REVISION 8 was written to
    address (a signal firing with only 5-10 minutes of session left to
    run the trade plan) is back in play for any signal firing in the
    last 30 minutes of the session.
Both values remain plain module constants (VOLUME_SPIKE_MULT,
SESSION_TIME_CUTOFF) so they can be tuned again the same way. The
"LOCKED as of 2026-08-25" language on Layer 1 above predates this
request and was written to prevent curve-fitting against a single day's
backtest results -- it does not apply to a direct operator instruction
to change live risk parameters.

=====================================================================
REVISION 10 (2026-08-27): execution cutoff split out from the Layer 1
session-time gate, per explicit user request
=====================================================================
The $150-account Monday-Wednesday what-if simulation run against
REVISION 9's loosened gate surfaced a real gap: signals now legally fire
right up to 20:00:00 UTC (the session close itself), but a signal firing
in, say, the last 5 minutes of the session has no more same-day option
data to run the exit plan against -- the position holds overnight. Two
concrete consequences showed up in that simulation: (1) all three
REVISION-9-only signals (GLW, DELL, TGT) exited via the 30-minute
TIME_DECAY_BACKSTOP at the NEXT trading day's session-open premium
rather than any same-day stop/target, and (2) TGT's overnight gap lost
-27.34%, blown through the -15% hard stop, because the backstop fired
before the hard stop got evaluated on that first post-gap bar (see
exit_engine.py REVISION 1, same date, which fixes the check-ordering
half of this).

Rather than re-tightening SESSION_TIME_CUTOFF itself (which would also
suppress signal DETECTION/logging in that window -- valuable data even
when the bot doesn't trade it), this revision splits the concern in two:
  - SESSION_TIME_CUTOFF (Layer 1, still 20:00:00 UTC) keeps gating
    whether a signal is detected and logged at all.
  - EXECUTION_CUTOFF (new, 19:30:00 UTC -- REVISION 8's original value)
    gates whether a logged signal is eligible for AUTOMATED EXECUTION.
    check_execution_time() implements this; it is called by
    live_prepare_order.py, separately from and after the three Layer 1
    checks, and is NOT part of evaluate_contract()'s layer1_checks dict.
A signal firing between 19:30:00 and 20:00:00 UTC therefore now gets
logged (Layer 1 passes) but not auto-executed (execution gate fails) --
visible in trade_log.jsonl as a distinct event so it isn't confused with
either a genuine risk-check rejection or a real prepared order.
"""

from dataclasses import dataclass, field

VERSION_LABEL = "the best one yet"

# ---------------------------------------------------------------------
# LAYER 1 -- Market Quality (binary, non-negotiable). LOCKED as of
# 2026-08-25 -- these three values are not to be tuned live against any
# single day's signals. Only a multi-week backtest with known outcomes
# should move them from here.
# ---------------------------------------------------------------------
RVOL_MIN = 0.75                # time-of-day-relative RVOL floor -- lowered from 1.0 as part of
                               # REVISION 5's OR-gate (see below); the 30d-avg-volume denominator
                               # comes from the "day" interval feed, which runs ~1.9x-6.4x (median
                               # 2.65x) higher than the SAME day's regular-session intraday bars
                               # summed -- likely consolidated-tape vs. primary-exchange-only
                               # reporting. volume_so_far in a live bot can only ever be intraday-
                               # sourced, so it can structurally never reach a same-day RVOL of 1.0x
                               # against that denominator. 0.75x plus the volume-spike OR-clause
                               # keeps this check meaningful without pretending the mismatch away.
VOLUME_SPIKE_MULT = 1.4       # REVISION 5: signal-bar volume must be >= this many times the
                               # trailing 20-bar volume moving average to satisfy the spike clause.
                               # Both sides come from the SAME intraday bar feed (at whatever
                               # interval -- 5/10/30min -- the signal fired on), so this side of the
                               # OR-gate has no cross-feed accounting mismatch at all.
                               # LOWERED from 2.0x to 1.4x on 2026-08-26 per explicit user request
                               # (not a backtest-driven change -- see REVISION 9 note below).
VOLUME_SPIKE_LOOKBACK = 20    # bars, at the signal's own interval
RVOL_HARD_FLOOR = 0.50        # REVISION 6: the volume-spike clause can only pass a signal if
                               # time-of-day RVOL is ALSO at least this -- guards against a single
                               # spiky bar on top of an otherwise dead-quiet session.
ATR_PCT_MIN = 2.0             # DAILY ATR(14) as % of price -- NOT 5-min-bar ATR (see check_atr_pct docstring
                               # for why 5-min-bar ATR was rejected as the wrong metric on 2026-08-25).
                               # Answers "does this stock move enough per day to justify buying options on
                               # it," not "was it choppy in the last 70 minutes." A tight pre-breakout
                               # consolidation should not suppress this number the way it would 5-min ATR.
SESSION_MINUTES = 390.0       # 13:30-20:00 UTC regular session
SESSION_TIME_CUTOFF = "20:00:00"  # REVISION 8: reject signals firing after this (UTC, HH:MM:SS).
                               # Structural scheduling rule, not a tuned constant -- see REVISION 8
                               # in the module docstring. EXTENDED from 19:30:00 to 20:00:00 (the
                               # regular-session close itself) on 2026-08-26 per explicit user
                               # request -- this effectively disables the cutoff, since no signal
                               # can fire after the session closes anyway. See REVISION 9 note below.
                               # Exactly 20:00:00 stays eligible (boundary,
                               # not past it); the regular session closes at 20:00:00 UTC.
                               # NOTE (REVISION 10): this Layer 1 gate controls SIGNAL DETECTION
                               # only -- whether a signal is logged at all. It does NOT control
                               # whether a detected signal is automatically executed; that's a
                               # separate, tighter gate -- see EXECUTION_CUTOFF /
                               # check_execution_time() below.
EXECUTION_CUTOFF = "19:30:00"  # REVISION 10 (2026-08-27): the $150-account Monday-Wednesday
                               # simulation (see diag/backtest/ dollar-simulation findings,
                               # 2026-08-26) showed that a signal firing on the session's last
                               # 5-minute bar (19:55 UTC, now legal again under REVISION 9's
                               # 20:00:00 SESSION_TIME_CUTOFF) holds the position overnight, since
                               # there's no more same-day option data to manage the exit plan
                               # against. Per explicit user request, the scanner keeps watching
                               # through SESSION_TIME_CUTOFF (20:00:00 UTC) and still LOGS any
                               # signal that fires there, but AUTOMATED EXECUTION is now gated
                               # separately and more tightly: a signal timestamped after
                               # EXECUTION_CUTOFF (19:30:00 UTC) is logged as signal-only and
                               # excluded from live_prepare_order.py's order-preparation path, so
                               # the bot never opens a position it can't finish managing the same
                               # session. This restores REVISION 8's original 19:30:00 boundary,
                               # but as an execution gate layered on top of Layer 1 rather than as
                               # part of Layer 1 itself -- Layer 1 (signal detection) and the
                               # execution decision are now two independently tunable cutoffs.
                               # check_execution_time() implements this; it is NOT one of the
                               # three Layer 1 checks and does not affect evaluate_contract()'s
                               # layer1_checks dict -- it is called separately by
                               # live_prepare_order.py before any risk check runs.

# Empirical cumulative-volume-fraction curve, one point per 5-min bar from
# session open (13:30 UTC) through close (19:55-20:00 UTC bar), measured
# from the Phase 1 backtest dataset (123 mover-day events, 45 symbols,
# 2026-07-27 to 2026-08-24 -- see diag/backtest/build_volume_curve.py).
# Replaces the old linear "elapsed_minutes/390" assumption in
# check_rvol_relative -- see REVISION 4 above for why. index i = the
# cumulative fraction of a full day's volume expected by the CLOSE of the
# (i+1)-th 5-minute bar, i.e. by minute (i+1)*5.
EMPIRICAL_CUM_VOL_FRAC = [
    0.057240, 0.087051, 0.112195, 0.136549, 0.158842, 0.177961, 0.199145,
    0.216427, 0.235083, 0.251908, 0.267714, 0.283003, 0.297284, 0.312142,
    0.325212, 0.337956, 0.350521, 0.361709, 0.373328, 0.384802, 0.396926,
    0.407568, 0.418029, 0.429651, 0.440915, 0.450361, 0.459954, 0.469505,
    0.478090, 0.486382, 0.496170, 0.507195, 0.516714, 0.525329, 0.533577,
    0.542989, 0.551550, 0.559055, 0.567055, 0.574820, 0.583165, 0.591653,
    0.598973, 0.606116, 0.613513, 0.619988, 0.627157, 0.634035, 0.641617,
    0.649053, 0.656629, 0.663601, 0.669794, 0.676377, 0.685274, 0.694209,
    0.701697, 0.709724, 0.715795, 0.723273, 0.731403, 0.738892, 0.746203,
    0.754255, 0.762068, 0.770800, 0.780529, 0.789835, 0.799480, 0.810150,
    0.821568, 0.832871, 0.846877, 0.860959, 0.874668, 0.892083, 0.920524,
    1.000000,
]  # 78 points, 5 min apart

# ---------------------------------------------------------------------
# LAYER 2 -- Contract Selection. Also reset to principled values.
# REFERENCE_PRICE anchors the %-scaled gamma band to a $100 stock so it
# reproduces the original fixed-dollar band at that reference point.
# ---------------------------------------------------------------------
REFERENCE_PRICE = 100.0
THETA_PCT_MIN = -8.0         # reset from the tuned -35.0 -- back to the original 1:1 translation of -$0.08 on ~$1 premium
SPREAD_ABS_MAX = 0.05
SPREAD_PCT_MAX = 0.10        # reset from the tuned 0.30 -- back to the original 10%
VEGA_PCT_MAX = 10.0          # never tuned
GAMMA_BAND_LO = 0.05         # never tuned
GAMMA_BAND_HI = 0.15

DELTA_CALL_LO = 0.35         # reset from the tuned [0.25, 0.55] -- standard liquidity band
DELTA_CALL_HI = 0.55
DELTA_PUT_LO = -0.55
DELTA_PUT_HI = -0.35


@dataclass
class FilterResult:
    passed: bool
    layer1_passed: bool = None
    layer2_passed: bool = None          # None if Layer 2 was never reached (Layer 1 failed)
    stopped_at: str = None              # "layer1" if rejected before Layer 2 ran, else None
    layer1_checks: dict = field(default_factory=dict)   # name -> (passed, detail)
    layer2_checks: dict = field(default_factory=dict)   # name -> (passed, detail) -- empty if stopped at layer1
    advisory: dict = field(default_factory=dict)        # name -> (passed | None, detail) -- never gates either layer

    def summary(self):
        lines = [f"[{VERSION_LABEL}]"]
        lines.append(f"LAYER 1 (Market Quality): {'PASS' if self.layer1_passed else 'FAIL'}")
        for name, (ok, detail) in self.layer1_checks.items():
            lines.append(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        if self.stopped_at == "layer1":
            lines.append("LAYER 2 (Contract Selection): NOT EVALUATED -- stopped at Layer 1")
        else:
            lines.append(f"LAYER 2 (Contract Selection): {'PASS' if self.layer2_passed else 'FAIL'}")
            for name, (ok, detail) in self.layer2_checks.items():
                lines.append(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        for name, (ok, detail) in self.advisory.items():
            tag = "ADVISORY-PASS" if ok else ("ADVISORY-FAIL" if ok is not None else "ADVISORY-N/A")
            lines.append(f"{tag}  {name}: {detail}")
        return "\n".join(lines)


def compute_peg_approx(pe_ratio, net_income_current, net_income_prior_yoy):
    """
    Trailing-growth PEG approximation. Returns (peg, note).
    peg is None when growth is negative/zero (PEG undefined/not meaningful).
    """
    if pe_ratio is None or net_income_prior_yoy in (None, 0):
        return None, "missing data"
    if net_income_prior_yoy < 0:
        return None, "prior-year net income was negative -- growth % not meaningful"
    growth_pct = (net_income_current - net_income_prior_yoy) / abs(net_income_prior_yoy) * 100
    if growth_pct <= 0:
        return None, f"YoY net income growth is {growth_pct:.1f}% (negative) -- PEG undefined"
    peg = pe_ratio / growth_pct
    note = f"PE={pe_ratio:.2f} / growth={growth_pct:.1f}% = {peg:.4f}"
    if growth_pct > 200:
        note += "  [WARNING: extreme growth% off a small prior-year base -- PEG likely distorted/meaningless]"
    if pe_ratio < 0:
        note += "  [WARNING: trailing PE is negative (trailing-12mo net income is negative) -- PEG sign is an artifact, not meaningful]"
    return peg, note


# ---------------------------------------------------------------------
# LAYER 1 checks -- market quality
# ---------------------------------------------------------------------

def _empirical_cum_vol_frac(elapsed_minutes, session_minutes=SESSION_MINUTES):
    """Look up the empirically-measured fraction of a full day's volume
    expected to have printed by elapsed_minutes into the session, via
    EMPIRICAL_CUM_VOL_FRAC (linearly interpolated between its 5-min
    points, with an implicit (elapsed=0, frac=0) origin point before the
    curve's first entry). Replaces the old flat
    elapsed_minutes/session_minutes assumption -- see REVISION 4 in the
    module docstring."""
    n = len(EMPIRICAL_CUM_VOL_FRAC)
    slot_width = session_minutes / n  # 5.0 minutes
    # pos is the position in units of "slots", where pos=0 is session open
    # (frac=0) and pos=k (k=1..n) lines up with EMPIRICAL_CUM_VOL_FRAC[k-1]
    # (the cumulative fraction by the close of the k-th 5-min bar).
    pos = max(0.0, min(elapsed_minutes, session_minutes)) / slot_width
    lo_idx = int(pos)          # integer slot boundary at or below pos
    frac_within = pos - lo_idx  # how far past that boundary, in [0, 1)
    v_lo = 0.0 if lo_idx == 0 else EMPIRICAL_CUM_VOL_FRAC[lo_idx - 1]
    hi_idx = min(lo_idx + 1, n)
    v_hi = EMPIRICAL_CUM_VOL_FRAC[hi_idx - 1] if hi_idx >= 1 else 0.0
    return v_lo + (v_hi - v_lo) * frac_within


def _time_of_day_rvol(volume_so_far, avg_volume_30d, elapsed_minutes, session_minutes=SESSION_MINUTES):
    """Time-of-day-relative RVOL, using the EMPIRICAL intraday cumulative-
    volume-fraction curve (EMPIRICAL_CUM_VOL_FRAC) instead of a linear
    elapsed_minutes/session_minutes assumption -- see REVISION 4 in the
    module docstring. Returns (rvol_or_None, note). rvol is None when it
    cannot be computed (missing avg_volume_30d or elapsed_minutes == 0).

    NOTE (REVISION 5): avg_volume_30d is sourced from the "day" interval
    feed, which runs ~1.9x-6.4x (median 2.65x) higher than the SAME day's
    intraday bars summed -- see REVISION 5 in the module docstring. This
    clause is therefore structurally biased low; it is one half of an
    OR-gate in check_volume_confirmation, not used standalone.
    """
    if not avg_volume_30d:
        return None, "missing avg_volume_30_days"
    expected_frac = _empirical_cum_vol_frac(elapsed_minutes, session_minutes)
    expected_by_now = avg_volume_30d * expected_frac
    if not expected_by_now:
        return None, "elapsed_minutes is 0 -- cannot compute time-of-day-relative expectation"
    rvol = volume_so_far / expected_by_now
    return rvol, (f"rvol={rvol:.2f}x ({volume_so_far:,.0f} vs expected {expected_by_now:,.0f} "
                  f"= {expected_frac*100:.1f}% of 30d-avg {avg_volume_30d:,.0f} [empirical curve, "
                  f"NOTE: denominator basis runs ~2.65x high vs. intraday feed -- see REVISION 5])")


def check_volume_confirmation(volume_so_far, avg_volume_30d, elapsed_minutes,
                               signal_bar_volume, recent_bar_volumes,
                               session_minutes=SESSION_MINUTES):
    """REVISION 5/6 OR-gate with hard floor: PASS if EITHER the time-of-
    day-relative RVOL clears RVOL_MIN (0.75x, empirical curve) OR BOTH (a)
    the signal's own bar carries >= VOLUME_SPIKE_MULT (2.0x) times the
    trailing VOLUME_SPIKE_LOOKBACK-bar (20-bar) volume moving average, at
    whatever interval the signal fired on, AND (b) RVOL is at least
    RVOL_HARD_FLOOR (0.50x) -- REVISION 6's guardrail against a single
    spiky bar on an otherwise dead-quiet session. The two clauses use
    different data bases on purpose: RVOL cross-checks against the
    30-day-average feed (day-bar sourced, run structurally high per
    REVISION 5); the spike clause never leaves the intraday feed, so it
    has no cross-feed mismatch and can confirm a real burst of
    participation even on a day where RVOL's denominator is inflated --
    but only above the 0.50x floor, so it can't rescue a truly dead day.

    recent_bar_volumes: the trailing bars' volumes (same interval as
    signal_bar_volume, e.g. all 5-min/10-min/30-min bar volumes strictly
    BEFORE the signal bar), most-recent-last or in any order -- only the
    values matter. Uses however many are available, up to
    VOLUME_SPIKE_LOOKBACK (fewer than that near the start of a session is
    fine, just a shorter lookback).
    """
    rvol, rvol_note = _time_of_day_rvol(volume_so_far, avg_volume_30d, elapsed_minutes, session_minutes)
    rvol_ok = rvol is not None and rvol >= RVOL_MIN
    rvol_clears_floor = rvol is not None and rvol >= RVOL_HARD_FLOOR

    spike_raw_ok = False
    if recent_bar_volumes:
        lookback = recent_bar_volumes[-VOLUME_SPIKE_LOOKBACK:]
        avg_bar_vol = sum(lookback) / len(lookback)
        spike_ratio = (signal_bar_volume / avg_bar_vol) if avg_bar_vol else 0.0
        spike_raw_ok = avg_bar_vol > 0 and spike_ratio >= VOLUME_SPIKE_MULT
        spike_note = (f"signal_bar_volume={signal_bar_volume:,.0f} vs trailing "
                       f"{len(lookback)}-bar avg {avg_bar_vol:,.0f} = {spike_ratio:.2f}x, "
                       f"need >= {VOLUME_SPIKE_MULT}x")
    else:
        spike_note = "no trailing bar-volume history available -- spike clause skipped"

    spike_ok = spike_raw_ok and rvol_clears_floor
    floor_note = (f"rvol_hard_floor: {'PASS' if rvol_clears_floor else 'FAIL'} "
                  f"(rvol={'N/A' if rvol is None else f'{rvol:.2f}x'}, need >= {RVOL_HARD_FLOOR}x)")

    ok = rvol_ok or spike_ok
    note = (f"[{'PASS' if rvol_ok else 'fail'}] {rvol_note}  OR  "
            f"[{'PASS' if spike_ok else 'fail'}] ({spike_note} AND {floor_note})  =>  {'PASS' if ok else 'FAIL'}")
    return ok, note
# NOTE (REVISION 7): check_volume_confirmation (and the _time_of_day_rvol /
# EMPIRICAL_CUM_VOL_FRAC machinery it depends on) is no longer called by
# evaluate_contract's Layer 1 gate -- left in place, unused, in case a real
# time-of-day volume-profile data source gets integrated later. See
# check_volume_impulse() below for what Layer 1 actually calls now.


def check_volume_impulse(signal_bar_volume, recent_bar_volumes):
    """REVISION 7: Layer 1's standalone volume check -- no session RVOL,
    no historical time-of-day baseline, no cross-feed accounting at all.
    PASS if the signal's own bar carries >= VOLUME_SPIKE_MULT (1.4x as of
    REVISION 9, 2026-08-26) the trailing VOLUME_SPIKE_LOOKBACK-bar (20-bar)
    volume moving average, at
    whatever interval (5/10/30min) the signal fired on. Runs natively off
    the same intraday bars this pipeline already pulls -- see REVISION 7
    in the module docstring for why session-cumulative RVOL was dropped
    from the gate (data-source limitation, not a strategy flaw).

    recent_bar_volumes: the trailing bars' volumes (same interval as
    signal_bar_volume, strictly BEFORE the signal bar), any order -- only
    the values matter. Uses however many are available, up to
    VOLUME_SPIKE_LOOKBACK (fewer near the start of a session is fine,
    just a shorter lookback).
    """
    if not recent_bar_volumes:
        return False, "no trailing bar-volume history available -- cannot evaluate volume impulse"
    lookback = recent_bar_volumes[-VOLUME_SPIKE_LOOKBACK:]
    avg_bar_vol = sum(lookback) / len(lookback)
    if not avg_bar_vol:
        return False, f"trailing {len(lookback)}-bar average volume is 0 -- cannot evaluate volume impulse"
    ratio = signal_bar_volume / avg_bar_vol
    ok = ratio >= VOLUME_SPIKE_MULT
    return ok, (f"signal_bar_volume={signal_bar_volume:,.0f} vs trailing {len(lookback)}-bar avg "
                f"{avg_bar_vol:,.0f} = {ratio:.2f}x, need >= {VOLUME_SPIKE_MULT}x")


def check_atr_pct(atr, price):
    """ATR as % of underlying price -- "does this stock move enough per day
    to justify buying options on it."
    IMPORTANT: pass DAILY ATR(period=14) here, not 5-minute-bar ATR. The
    2.0% floor is calibrated against typical daily range. 5-min-bar ATR
    (bar-to-bar chop over the last ~70 minutes) runs at a completely
    different scale (~0.15-0.9% of price even on a stock having a big
    trending day), rejects everything against a %-of-price floor meant
    for daily range, AND penalizes a stock that consolidated tightly
    right before a real breakout -- exactly the setup this bot wants to
    catch. Both problems (metric mismatch, and pre-breakout consolidation
    false-rejection) were found and fixed on 2026-08-25 by switching to
    daily ATR here."""
    if not price:
        return False, "missing underlying price"
    atr_pct = atr / price * 100
    ok = atr_pct >= ATR_PCT_MIN
    return ok, f"atr=${atr:.4f} ({atr_pct:.3f}% of price ${price:.2f}), need >= {ATR_PCT_MIN:.2f}%"


def check_session_time(signal_timestamp, cutoff=SESSION_TIME_CUTOFF):
    """REVISION 8: Layer 1's session-time cutoff -- structural, not tuned
    (see REVISION 8 in the module docstring). PASS if the signal's own
    timestamp is at/before `cutoff` (default 20:00:00 UTC as of REVISION 9,
    2026-08-26 -- the regular-session close itself, which effectively
    disables this gate; was 19:30:00, 30 minutes before the 20:00:00 UTC
    regular-session close, prior to that). FAIL (not skip) if no
    timestamp is supplied at all -- this mirrors check_volume_impulse's
    treatment of missing recent_bar_volumes: a check this file's own
    backtest showed matters gets enforced, not silently bypassed when the
    caller forgets to wire it up.

    signal_timestamp: any string with 'HH:MM:SS' at character offset
    11-19 -- both formats seen in this repo work directly, no parsing
    library needed: ISO 'YYYY-MM-DDTHH:MM:SSZ' and pandas/Robinhood's
    'YYYY-MM-DD HH:MM:SS+00:00'.
    """
    if not signal_timestamp:
        return False, "no signal timestamp provided -- cannot evaluate session-time cutoff"
    hms = signal_timestamp[11:19]
    try:
        h, m, sec = (int(x) for x in hms.split(":"))
    except (ValueError, IndexError):
        return False, f"could not parse HH:MM:SS from signal_timestamp={signal_timestamp!r}"
    cutoff_h, cutoff_m, cutoff_s = (int(x) for x in cutoff.split(":"))
    t_minutes = h * 60 + m + sec / 60.0
    cutoff_minutes = cutoff_h * 60 + cutoff_m + cutoff_s / 60.0
    ok = t_minutes <= cutoff_minutes
    if ok:
        return True, f"signal fires at {hms} UTC, at/before the {cutoff} UTC late-session cutoff"
    return False, (f"signal fires at {hms} UTC, {t_minutes - cutoff_minutes:.0f} min after the "
                    f"{cutoff} UTC late-session cutoff -- only {max(0.0, 20*60 - t_minutes):.0f} min "
                    f"left to the 20:00:00 UTC session close, not enough runway to manage the trade plan")


def check_execution_time(signal_timestamp, cutoff=EXECUTION_CUTOFF):
    """REVISION 10: the AUTOMATED-EXECUTION gate, separate from Layer 1's
    check_session_time() above. A signal can pass every Layer 1 check
    (including session_time against the looser 20:00:00 SESSION_TIME_CUTOFF)
    and still be correctly logged, yet still fail THIS check -- that's by
    design. It exists because a signal firing after 19:30:00 UTC has no
    same-day option data left to run the exit-management plan against: the
    position would hold overnight with no way to manage it until the next
    session opens.

    PASS if signal_timestamp is at/before `cutoff` (default 19:30:00 UTC).
    FAIL (not skip) if no timestamp is supplied, same convention as
    check_session_time(). Callers (currently just live_prepare_order.py)
    should treat a FAIL here as "log signal-only, do not prepare an order"
    -- NOT as a rejected proposal in the same sense as a failed risk check,
    since nothing about the signal or the contract was actually wrong.

    signal_timestamp: same accepted formats as check_session_time().
    """
    if not signal_timestamp:
        return False, "no signal timestamp provided -- cannot evaluate execution cutoff"
    hms = signal_timestamp[11:19]
    try:
        h, m, sec = (int(x) for x in hms.split(":"))
    except (ValueError, IndexError):
        return False, f"could not parse HH:MM:SS from signal_timestamp={signal_timestamp!r}"
    cutoff_h, cutoff_m, cutoff_s = (int(x) for x in cutoff.split(":"))
    t_minutes = h * 60 + m + sec / 60.0
    cutoff_minutes = cutoff_h * 60 + cutoff_m + cutoff_s / 60.0
    ok = t_minutes <= cutoff_minutes
    if ok:
        return True, f"signal fires at {hms} UTC, at/before the {cutoff} UTC execution cutoff -- eligible for automated execution"
    return False, (f"signal fires at {hms} UTC, {t_minutes - cutoff_minutes:.0f} min after the "
                    f"{cutoff} UTC execution cutoff -- logged as signal-only, not eligible for "
                    f"automated execution (would hold overnight with no same-day exit-management runway)")


def check_vwap_alignment(entry_price, vwap_at_entry, direction):
    """Binary price-confirmation check -- not a tunable threshold. If price
    is on the wrong side of VWAP for the signaled direction, the market
    structure is actively contradicting the trade at entry."""
    if direction == "call":
        ok = entry_price > vwap_at_entry
        return ok, f"entry={entry_price:.2f} vs vwap={vwap_at_entry:.2f}, calls need entry ABOVE vwap"
    else:
        ok = entry_price < vwap_at_entry
        return ok, f"entry={entry_price:.2f} vs vwap={vwap_at_entry:.2f}, puts need entry BELOW vwap"


# ---------------------------------------------------------------------
# LAYER 2 checks -- contract selection (only run if Layer 1 passes)
# ---------------------------------------------------------------------

def check_delta(delta, direction):
    lo, hi = (DELTA_CALL_LO, DELTA_CALL_HI) if direction == "call" else (DELTA_PUT_LO, DELTA_PUT_HI)
    ok = lo <= delta <= hi
    return ok, f"delta={delta:.4f}, need [{lo}, {hi}]"


def check_theta_pct(theta, mark):
    """theta as % of premium, instead of fixed -$0.08."""
    if not mark:
        return False, "missing mark price"
    theta_pct = theta / mark * 100
    ok = theta_pct >= THETA_PCT_MIN
    return ok, f"theta={theta:.4f} ({theta_pct:.2f}% of mark ${mark:.2f}), need >= {THETA_PCT_MIN:.1f}%"


def check_gamma_pct(gamma, price):
    """gamma band scaled inversely with underlying price (anchored so a
    $100 stock reproduces the original [0.05, 0.15] band)."""
    if not price:
        return False, "missing underlying price"
    lo = GAMMA_BAND_LO * (REFERENCE_PRICE / price)
    hi = GAMMA_BAND_HI * (REFERENCE_PRICE / price)
    ok = lo <= gamma <= hi
    return ok, f"gamma={gamma:.6f}, need [{lo:.6f}, {hi:.6f}] (scaled band @ price=${price:.2f})"


def check_vega_pct(vega, mark):
    """vega as % of premium, instead of fixed $0.10 absolute."""
    if not mark:
        return False, "missing mark price"
    vega_pct = abs(vega) / mark * 100
    ok = vega_pct <= VEGA_PCT_MAX
    return ok, f"vega={vega:.4f} ({vega_pct:.2f}% of mark ${mark:.2f}), need <= {VEGA_PCT_MAX:.1f}%"


def check_spread(bid, ask, mark):
    spread = ask - bid
    pct_of_mark = (spread / mark) if mark else float("inf")
    ok = (spread <= SPREAD_ABS_MAX) or (pct_of_mark <= SPREAD_PCT_MAX)
    return ok, (f"spread=${spread:.2f} ({pct_of_mark*100:.1f}% of mark), "
                f"need <= ${SPREAD_ABS_MAX:.2f} OR <= {SPREAD_PCT_MAX*100:.0f}% of mark")


def check_peg_advisory(peg, direction):
    """PEG is informational only -- returns (ok_or_None, detail). ok is None
    when PEG is undefined (cannot be evaluated either way); this never gates
    either layer."""
    if peg is None:
        return None, "PEG undefined/not meaningful -- advisory only, does not block the contract"
    if direction == "call":
        ok = peg <= 1.50
        return ok, f"peg={peg:.4f}, advisory target <= 1.50 (call)"
    else:
        ok = peg >= 2.00
        return ok, f"peg={peg:.4f}, advisory target >= 2.00 (put)"


def evaluate_contract(direction, delta, theta, gamma, vega, peg, volume_so_far, avg_volume_30d,
                       elapsed_minutes, atr, bid, ask, mark, entry_price, vwap_at_entry,
                       signal_bar_volume=None, recent_bar_volumes=None,
                       underlying_price=None, signal_timestamp=None):
    """
    direction: "call" or "put"
    underlying_price: current underlying price, used for the %-scaled gamma
        check and the advisory ATR%. Defaults to entry_price if not given
        separately.
    signal_bar_volume, recent_bar_volumes: the signal's own bar's volume
        and the trailing bars' volumes (same interval, strictly before
        the signal bar) -- REVISION 7: this is now Layer 1's ONLY volume
        check (check_volume_impulse), not one half of an OR-gate. Missing/
        empty recent_bar_volumes fails this check (cannot evaluate).
    signal_timestamp: the signal's own timestamp (any string with
        'HH:MM:SS' at offset 11-19). REVISION 8: gates Layer 1 via
        check_session_time -- missing this FAILS the check, same
        fail-closed treatment as missing recent_bar_volumes above.

    Two-layer evaluation:
      LAYER 1 (market quality: volume_impulse, vwap, session_time) runs
      first -- REVISION 7 dropped ATR (redundant with the upstream movers
      filter) and session-cumulative RVOL (hobbled by a data-source
      limitation, not a strategy flaw -- see REVISION 7 in the module
      docstring) from the gate; REVISION 8 added session_time (a
      structural scheduling rule, not a tuned constant -- see REVISION 8).
      If ANY Layer 1 check fails, evaluation STOPS -- Layer 2 is
      never computed, `passed` is False, and `stopped_at` is set to
      "layer1".
      LAYER 2 (contract selection: delta, theta_pct, gamma_pct, vega_pct,
      spread) only runs if Layer 1 fully passed. `passed` is then Layer 1 AND
      Layer 2.
      PEG and ATR% are always computed and reported as advisory,
      regardless of which layer the evaluation reaches or stops at --
      informational only, never gate either layer.
    """
    price = underlying_price if underlying_price is not None else entry_price

    layer1_checks = {}
    layer1_checks["volume_impulse"] = check_volume_impulse(signal_bar_volume, recent_bar_volumes or [])
    layer1_checks["vwap"] = check_vwap_alignment(entry_price, vwap_at_entry, direction)
    layer1_checks["session_time"] = check_session_time(signal_timestamp)
    layer1_passed = all(ok for ok, _ in layer1_checks.values())

    advisory = {}
    advisory["peg"] = check_peg_advisory(peg, direction)
    advisory["atr_pct"] = check_atr_pct(atr, price)

    if not layer1_passed:
        return FilterResult(passed=False, layer1_passed=False, layer2_passed=None,
                             stopped_at="layer1", layer1_checks=layer1_checks,
                             layer2_checks={}, advisory=advisory)

    layer2_checks = {}
    layer2_checks["delta"] = check_delta(delta, direction)
    layer2_checks["theta_pct"] = check_theta_pct(theta, mark)
    layer2_checks["gamma_pct"] = check_gamma_pct(gamma, price)
    layer2_checks["vega_pct"] = check_vega_pct(vega, mark)
    layer2_checks["spread"] = check_spread(bid, ask, mark)
    layer2_passed = all(ok for ok, _ in layer2_checks.values())

    return FilterResult(passed=(layer1_passed and layer2_passed), layer1_passed=True,
                         layer2_passed=layer2_passed, stopped_at=None,
                         layer1_checks=layer1_checks, layer2_checks=layer2_checks, advisory=advisory)
