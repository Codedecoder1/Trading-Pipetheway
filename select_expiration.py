"""
Expiration-selection policy for the live pipeline (2026-09-06), per
explicit user request.

WHY THIS EXISTS: the pipeline's long-standing convention was for the
calling session to grab "the nearest expiration's contract chain" -- in
practice often a 0-3 DTE weekly. The user wants roughly two weeks of time
value on every position: longer-dated calls/puts that can ride the
underlying up and down over ~3 weeks without theta gutting them in a day,
managed by the -15% hard stop (see live_prepare_order.py) rather than a
same-day close. This is the counterpart to contract_filters.py REVISION 11
(EXECUTION_CUTOFF raised to the session close, since a late entry no longer
needs same-day exit runway) and contract_selector.py REVISION 6 (ATM-first
again, now that the budget is back to 85% of buying power).

Pure function, no tool access -- same pattern as contract_selector.py /
live_risk_checks.py. The calling session fetches the list of available
expiration dates itself (get_option_chains) and passes them in.

Policy: pick the FIRST available expiration at least MIN_DTE calendar days
out and no more than MAX_DTE out. If nothing falls inside that window,
take the nearest expiration beyond MIN_DTE (better too long than too
short). Reject only when there is no expiration at least MIN_DTE out at
all -- the caller then logs the signal as signal-only and stops.
"""
from datetime import date, datetime

MIN_DTE = 10   # calendar days -- "about two weeks" once the weekend lands
MAX_DTE = 45   # don't reach for LEAPS-style far-dated contracts


def _as_date(d):
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def select_expiration(available_expirations, today=None):
    """
    available_expirations: iterable of 'YYYY-MM-DD' strings (or date/datetime).
    today: date; defaults to date.today().

    Returns (expiration_str, method, note):
      expiration_str: 'YYYY-MM-DD' of the chosen expiration, or None on reject.
      method: "IN_WINDOW" | "NEAREST_BEYOND_MIN" | "REJECTED_NOTHING_FAR_ENOUGH"
      note: human-readable reasoning, safe to log or drop in a notification.
    """
    if today is None:
        today = date.today()

    try:
        exps = sorted({_as_date(d) for d in available_expirations})
    except (ValueError, TypeError) as e:
        return None, "REJECTED_NOTHING_FAR_ENOUGH", f"could not parse expirations: {e!r}"

    if not exps:
        return None, "REJECTED_NOTHING_FAR_ENOUGH", "no expirations supplied"

    dated = [(d, (d - today).days) for d in exps]

    in_window = [(d, n) for d, n in dated if MIN_DTE <= n <= MAX_DTE]
    if in_window:
        d, n = in_window[0]
        return d.isoformat(), "IN_WINDOW", (
            f"{d.isoformat()} is {n} days out -- first expiration inside the "
            f"{MIN_DTE}-{MAX_DTE} day target window"
        )

    beyond_min = [(d, n) for d, n in dated if n >= MIN_DTE]
    if beyond_min:
        d, n = beyond_min[0]
        return d.isoformat(), "NEAREST_BEYOND_MIN", (
            f"{d.isoformat()} is {n} days out -- nothing inside {MIN_DTE}-{MAX_DTE}, "
            f"took the nearest expiration at least {MIN_DTE} days out"
        )

    nearest, n = dated[-1]
    return None, "REJECTED_NOTHING_FAR_ENOUGH", (
        f"no expiration at least {MIN_DTE} days out (furthest available is "
        f"{nearest.isoformat()}, only {n} days out) -- signal-only, no trade"
    )


if __name__ == "__main__":
    sample = ["2026-09-08", "2026-09-11", "2026-09-18", "2026-09-25", "2026-10-16"]
    for t in ("2026-09-06", "2026-09-14", "2026-10-10"):
        exp, method, note = select_expiration(sample, today=datetime.strptime(t, "%Y-%m-%d").date())
        print(f"today {t}: -> {exp}  [{method}]")
        print(f"   {note}")
