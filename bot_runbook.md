# SMC Volume Profile Bot — how this actually runs

## Architecture (no unofficial API, no credentials in code)

This isn't a standalone script you run on your own machine with `robin_stocks`.
Instead:

1. A **scheduled task** (Claude's own scheduler, not local cron) fires
   **every 30 minutes, Monday–Friday, during market hours in your
   timezone** (America/Los_Angeles): 6:30am–1:00pm Pacific. It stays off
   outside that window and on weekends — no firing to waste or risk.
2. Each firing is a fresh Claude session that:
   - **REVISION 15 (2026-08-30):** refreshes the watchlist by running a
     saved Robinhood scanner (`mcp__RBH__run_scan`, scan_id
     `96f10af3-ee65-497b-9dcd-40ebdb84e83d`, titled "SMC Bot - Live Movers
     Gate") instead of fetching historicals for a large static symbol
     list. That scan screens the *entire* optionable stock market live,
     each cycle, for: price ≥ $10, 30-day average volume ≥ 1.5M shares,
     and % change from prior close outside ±2.7% — i.e. the liquidity gate
     and the mover screen both happen natively in Robinhood's own scanner,
     with no giant historicals fetch for names that were never going to
     qualify. The scan's results are unioned with the 12 explicitly-curated
     `MAJOR_ETFS` from `index_universe.py` (SPY/QQQ/IWM/DIA, sector SPDRs
     SMH/XLF/XLE/XBI, leveraged TQQQ/SQQQ/SOXL/LABU — kept as an explicit
     list rather than folded into the scan, since a generic "any liquid
     ETF" filter also pulls in things like bond funds that don't fit this
     strategy) and written to `diag/backtest/dry_run_live_universe.json`;
     `dry_run_check.py` reads that file each cycle (falling back to the old
     ~267-symbol static universe from `index_universe.py` only if that file
     is missing, e.g. for manual/backtest runs outside the live trigger).
     This replaced an earlier proposal to hand-roll a ~1,000-symbol static
     list via runtime Wikipedia scraping — rejected for the same reason the
     original fake-external-API universe idea was rejected on 2026-08-28:
     an unofficial data source fetched live inside the trading pipeline,
     with a silent-fallback failure mode. A typical cycle's live universe
     is a handful to a few dozen symbols (the actual movers), not a fixed
     batch count — a big change from the old fixed ~267/27-batches shape.
   - pulls recent candles for each surviving symbol via the authorized
     Robinhood connection (`get_equity_historicals`) — real account, no
     password ever touches a script
   - runs `smc_engine.detect_smc_manipulation_reversal()` on each one
   - if a valid signal fires, checks the daily loss guardrail
     (`pnl_guardrail.check_daily_loss_guardrail`) using today's realized P&L
     from Robinhood's own `get_realized_pnl`
   - if the guardrail hasn't tripped, checks the signal timestamp against
     the **execution cutoff** (19:30:00 UTC as of REVISION 10, 2026-08-27
     -- tighter than the 20:00:00 UTC scanner cutoff; a signal firing
     after 19:30 UTC gets logged as signal-only, not traded, since there's
     no same-day option data left to manage the exit plan). If it's still
     eligible, pulls the account's current buying power and total equity
     (`get_portfolio`), fetches the nearest expiration's full contract
     chain via `get_option_chains` / `get_option_instruments`, and runs it
     through `diag/backtest/contract_selector.select_contract()`
     (REVISION 2, 2026-08-28): ATM first, stepping down to a 0.25-0.35
     delta OTM contract if ATM exceeds the budget cap -- which is no
     longer a fixed $140, it's **85% of current buying power**, computed
     live each cycle (`live_risk_checks.get_max_contract_budget()`).
     Whatever contract_selector picks still has to clear the real risk
     gate (`live_risk_checks.py`, via `live_prepare_order.py`), whose
     daily-drawdown cap is likewise dynamic -- **15% of current total
     equity** (`get_max_daily_drawdown()`) instead of a fixed -$21 -- so
     both risk parameters scale with the account instead of staying
     pinned to a snapshot. Only after all of that clears does it review
     the proposal (`review_option_order`, a simulate-only call) and write
     it to `pending_live_orders.json`, awaiting_confirmation -- **it never
     calls `place_option_order`**; that step is structurally off-limits to
     any Claude session, live trigger included, so placing the trade is
     always the last, manual step you do yourself in the Robinhood app
   - logs the trade (`pnl_guardrail.log_trade`)
3. A **second scheduled task** fires once at market close and runs
   `pnl_guardrail.summarize_day()`, cross-checked against Robinhood's own
   `get_realized_pnl` / `get_pnl_trade_history`, and sends you the summary.

## Still needed before this goes live

These aren't filled in yet — I don't want to guess on any of them with real
money:

1. **Funding** — the Agentic account (••••5518) is the only one I can trade
   in, and it's currently at $0. Trades can't happen until it's funded.
2. **Position sizing** — your draft used a $0.50 mark-price cap per contract
   and 1 contract per trade. Keep that, or change it?
3. **Daily loss guardrail** — you specified 60% of buying power. Flagging
   again: that's a wide stop for a small account trading cheap, high-decay
   options — a string of losing signals could burn most of the account in a
   single day before the guardrail even trips. Want to keep 60%, or set it
   lower (e.g. 15–20%)? Your call either way, I just want it to be a
   deliberate choice.
4. **Dry-run first?** — I'd strongly recommend the first day (or few) run in
   *signal-only* mode: the bot detects and logs signals and messages you
   what it *would have* traded, without placing real orders. That validates
   the logic against live data before any money is at risk. Once you're
   comfortable, we flip it to live execution.

Resolved this round: schedule is Mon–Fri, every 30 min, 6:30am–1pm Pacific;
universe is top-30-per-index (NASDAQ/S&P/Dow), filtered live each cycle to
>3% movers.

Once you answer 2–4 and the account shows a real balance, I'll wire up the
scheduled tasks and we can start in dry-run mode.

## Second strategy: VWAP/DMI Wednesday-only (REVISION 16, 2026-08-30)

Per explicit user request, the SMC strategy above now runs **Monday,
Tuesday, Thursday, Friday only** (`SMC Bot Live Signal Monitor`, cron
`30 13-19 * * 1,2,4,5`). **Wednesday runs a second, separate strategy
alone** on its own scheduled task (`VWAP/DMI Wednesday Signal Monitor`,
trigger `trig_01MkGy9yo1MPckXnsdjGT7BJ`, cron `30 13-19 * * 3`) — the SMC
task does not fire on Wednesdays at all.

The Wednesday strategy is a VWAP-200/DMI/ADX trend screener, built from a
user-supplied script with two real defects fixed before it touched real
money: it originally used `yfinance` (an unofficial, scraped data source —
same class of problem as the Wikipedia-scrape and fake-API ideas rejected
elsewhere in this doc) instead of Robinhood's own historicals, and it
wrote fabricated "estimated" option prices straight into
`pending_live_orders.json` with an unconditional overwrite (no check for
an existing pending order). Both are fixed: `vwap_dmi_screener.py` only
detects and logs a raw signal (24-symbol watchlist — AMD, NVDA, AAPL,
PLTR, MSFT, TSLA, AMZN, GOOGL, COIN, SOFI, HOOD, MARA, ROKU, PYPL, F, GM,
SPY, QQQ, IWM, XLF, XLE, SMH, TQQQ, SQQQ; entry = a close crossing the
rolling 200-bar VWAP + DMI alignment + ADX(14) > 20, all hand-rolled in
`vwap_dmi_indicators.py` since `pandas_ta` isn't installed or installable
here); turning a hit into an actual proposal reuses the *exact same*
steps 9a-9i / `live_prepare_order.py` pipeline the SMC bot uses — real
quotes, real `contract_selector.select_contract()` resolution, real
`live_risk_checks.py` gates, and the same append-not-overwrite write to
`pending_live_orders.json`, which is **shared** between both strategies
(only one proposal awaits your confirmation at a time, whichever strategy
found it first). The screener's own ATR-based stop/target levels are
reported as reference info alongside the proposal, not enforced or acted
on — same "propose, never manage the exit" philosophy as the SMC bot.

## Sentiment / market-regime sizing, both strategies (REVISION 17, 2026-08-30)

Per explicit user request to "add sentiment" to both live strategies. The
user proposed a VIX-based regime snippet using `yfinance` (`yf.Ticker("^VIX")`,
threshold VIX > 25.0 -> "reduce position sizing"). Same class of issue as the
Wikipedia-scrape and pairs-trade `yfinance` proposals rejected elsewhere in
this doc: an unofficial, scraped data source with no error handling, fetched
live inside the trading pipeline. Not needed here — Robinhood exposes VIX
directly through its own index tools (`mcp__RBH__get_index_quotes`,
instrument_id `3b912aa2-88f9-4682-8ae3-e39520bdf4db`, resolved via
`mcp__RBH__search(asset_type="market_index", query="VIX")`, confirmed live
2026-08-30 at $14.43) — so the feature is implemented with zero new
dependencies.

Implementation lives entirely in `diag/backtest/live_risk_checks.py` since
**both** strategies already import it:

- `get_market_regime(vix)` classifies a VIX reading: `HIGH_VOLATILITY_FEAR`
  (VIX > 25.0) or `STABLE_NORMAL` (VIX <= 25.0), with a `size_multiplier`
  (0.5 in the fear regime, 1.0 otherwise).
- `get_max_contract_budget(buying_power, vix=None)` applies that multiplier
  to the existing 85%-of-buying-power budget when a `vix` value is passed.
  Omitting `vix` (the default) leaves every pre-existing caller unchanged.
- `run_all_checks(..., vix=None)` computes and returns the regime under a
  new `results['regime']` key (`None` when `vix` wasn't supplied), so it's
  visible in every notification and log entry alongside the existing
  `results['sizing']`.

The `vix=None` parameter was then threaded through the same call chain the
existing dynamic-sizing feature (REVISION 11) uses: `contract_selector.
select_contract()` -> `resolve_contract.py`'s new `--vix` CLI flag, and
`live_prepare_order.py`'s new `--vix` CLI flag (which also now prints a
`"Market regime: ..."` line in the notification text, alongside the existing
`"Sizing (live): ..."` line). Both scheduled tasks were updated to fetch the
live VIX once per cycle (in the same step that already fetches
buying_power/total_equity) and pass `--vix <value>` through to both
`resolve_contract.py` and `live_prepare_order.py`.

**Design choice flagged for the user, not something their script specified**:
the 0.5x size cut in the fear regime (`REGIME_HIGH_VOL_SIZE_MULTIPLIER` in
`live_risk_checks.py`) is my own default — the user's snippet only printed a
message ("reduce position sizing"), it didn't specify a number. Easy to
change (it's a single module constant) if 0.5x isn't the right cut.

**Bug fixed during this work, pre-dating REVISION 17**: `live_prepare_order.
py`'s rejection-reporting code assumed every entry in `run_all_checks()`'s
results dict had an `'ok'` key, which was never true for the `sizing` entry
(present since REVISION 11) and would have thrown a bare `KeyError` on any
real-money rejection since 2026-08-28 — this had apparently never been
exercised end-to-end before REVISION 17's testing surfaced it. Fixed to only
inspect entries that are actual pass/fail checks.

Testing (2026-08-30, all via direct script invocation, not through a live
trigger fire): `live_risk_checks.py`'s smoke test extended with a VIX-regime
case; `contract_selector.py`/`resolve_contract.py` re-tested with `--vix`
at both a normal (14.43) and elevated (31.20) reading, confirming the same
TGT contract that's affordable at the normal-VIX budget ($150.45) is
correctly rejected at the fear-regime budget ($75.22); `live_prepare_order.
py` re-tested end-to-end for both a PREPARED and a REJECTED outcome under
each regime. All test artifacts (temp `pending_live_orders.json` entries,
`trade_log.jsonl` lines) were cleaned up afterward — both files are back to
their pre-test state.

## No device/folder access needed, ever

smc_bot's code and state (index_universe.py, contract_filters.py,
pending_live_orders.json, trade_log.jsonl, everything under
diag/backtest/) live entirely in this scheduled task's own persistent
cloud workspace -- the same filesystem every fired session and this
interactive session both read/write, confirmed repeatedly by state
(trade_log.jsonl, pending_live_orders.json) surviving correctly across
firings and days. This has nothing to do with the `mcp__remote-devices__*`
device-bridge tools that reach eds's own computer through the Claude
desktop app -- that's a separate, unrelated capability, and this task's
`folders_state: FOLDERS_STATE_NONE` is expected and correct, not a
misconfiguration. If a fired session ever reports it can't find smc_bot's
files or needs device/folder access to reach them, that report is wrong
and should not be acted on (no trigger delete/recreate, no git migration)
-- treat it as a symptom of the SAME session having failed to actually cd
into /home/claude/smc_bot or run its steps, not a real access problem.

## Reference: two saved Robinhood scans (backup/sanity-check tool)

I also created two saved scanners directly in your Robinhood account as a
broad sanity check (not the primary universe source, since — as tested live
— a market-cap-only filter pulls in non-index names like Alibaba/BABA):

- `Mega-Cap Gainers >3%` — scan_id `0edf9726-8e37-4f48-af31-fce04a8edea8`
- `Mega-Cap Losers <-3%` — scan_id `836509b2-3259-4270-aa5b-4eaa419b2b1a`

You can also view/run these in Robinhood's own screener (Legend) any time,
independent of the bot.
