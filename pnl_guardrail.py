"""
Trade logging + daily loss circuit breaker.

This is deliberately broker-agnostic bookkeeping. Authoritative fill prices
and realized P&L should come from Robinhood itself at close of day (via the
get_realized_pnl / get_pnl_trade_history tools on the authorized connection)
-- this module's log is the strategy-side record of *why* each trade was
taken, cross-checked against that authoritative number, not a replacement
for it.
"""

import csv
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


LOG_PATH = os.path.join(os.path.dirname(__file__), "trade_log.csv")


@dataclass
class TradeRecord:
    timestamp: str
    ticker: str
    signal_type: str          # BULLISH_POC_RETEST / BEARISH_POC_RETEST
    option_type: str          # call / put
    contract_symbol: str
    poc_price: float
    stop_price: float
    limit_price: float
    quantity: int
    status: str               # QUEUED / FILLED / CANCELLED / REJECTED
    realized_pnl: float = None  # filled in at close, from Robinhood's own numbers


def log_trade(record: TradeRecord):
    file_exists = os.path.isfile(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(record).keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(asdict(record))


def summarize_day(date_str: str = None):
    """
    Reads trade_log.csv and returns a per-trade list plus totals for the
    given date (defaults to today, UTC). Use this alongside Robinhood's own
    get_realized_pnl as the authoritative cross-check.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not os.path.isfile(LOG_PATH):
        return {"date": date_str, "trades": [], "total_realized_pnl": 0.0, "trade_count": 0}

    rows = []
    with open(LOG_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["timestamp"].startswith(date_str):
                rows.append(row)

    total = sum(float(r["realized_pnl"]) for r in rows if r.get("realized_pnl") not in (None, "", "None"))
    return {"date": date_str, "trades": rows, "total_realized_pnl": round(total, 2), "trade_count": len(rows)}


def check_daily_loss_guardrail(
    day_start_buying_power: float,
    realized_pnl_today: float,
    max_loss_pct: float = 0.10,
):
    """
    Returns (halt: bool, loss_pct: float).

    halt=True means: do not place any new trade for the rest of the day.
    Existing open positions are not force-closed by this check alone --
    that's a separate, explicit decision.

    2026-09-07 (Conservative dials, per explicit user request): lowered from
    0.60 to 0.10 -- once today's realized loss reaches 10% of day-start
    buying power, no new trades for the rest of the session. The old 0.60
    was effectively no guardrail at all on a small account (it allowed a
    ~$100 loss day on ~$168 buying power before halting).
    """
    if day_start_buying_power <= 0:
        return True, 0.0

    loss_pct = max(0.0, -realized_pnl_today) / day_start_buying_power
    halt = loss_pct >= max_loss_pct
    return halt, round(loss_pct * 100, 2)
