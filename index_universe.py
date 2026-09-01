"""
Static index-membership universe: top ~30 companies (by market cap) from
each of NASDAQ, the S&P 500, and the Dow Jones Industrial Average, PLUS
(added 2026-08-26 per explicit user request) five broader index lists:
Nasdaq-100 (also covers "QQQ top 100"), S&P 100, Russell Top 100, PHLX
Semiconductor (SOX) top 20, and KBW Bank Index (BKX).

WHY STATIC: the Robinhood scanner tools available in this session can
screen by market cap, sector, price, volume, and technicals, but there is
no "member of index X" filter and no live index-constituents endpoint.
A pure market-cap threshold pulls in non-index mega caps too (e.g. BABA /
Alibaba tested at $300B+ cap and got flagged as a "loser" despite not
being in any of these three indices). So membership is hand-maintained
here instead.

STALENESS: index composition changes a handful of times a year (Dow swaps
are rare but do happen; S&P 500 and Nasdaq-100 rebalance more often, and
"top 30 by market cap within an index" shifts whenever prices move). This
list reflects a recent, good-faith snapshot -- treat it as "needs a
periodic sanity check," not a live feed. Ask Claude to re-verify it every
few weeks, or whenever a name looks obviously wrong in the scan output.

SOURCES for the 2026-08-26 additions (each independently WebFetched, since
this session's search_first rule requires live lookups for anything that
changes over time -- training-data membership would already be stale):
  - NASDAQ_100: Wikipedia "Nasdaq-100" article, snapshot dated 2026-01-20
    in the source table (102 tickers incl. both GOOGL/GOOG share classes).
  - SP_100: user-supplied list (2026-08-26), pasted directly rather than
    scraped -- supersedes an earlier WebFetch attempt off the iShares OEF
    ETF holdings CSV (that CSV had its own issues: 5 trailing non-equity
    cash/futures overlay rows, one corrupted "HONA" row). 104 tickers as
    given by the user; used verbatim rather than reconciled against the
    commonly-cited "101 components" figure, since this is the
    authoritative source for this list.
  - RUSSELL_TOP_100: iShares IWL ETF (Russell Top 200) holdings CSV,
    fetched 2026-08-26, which returns holdings pre-sorted by weight
    (largest first) -- took exactly the first 100 rows. User explicitly
    chose "Russell Top 100" over "Top 200" after the raw ~200-row CSV
    turned out to carry the same handful of trailing non-equity/garbled
    rows as the S&P 100 CSV; restricting to the clean, weight-sorted top
    100 sidesteps that data-quality issue entirely.
  - SOX_TOP_20: nasdaq.com/docs/SOX PHLX Semiconductor Sector Index
    factsheet, dated 05/01/2026, top 20 of its 30 listed holdings by
    weight.
  - KBW_BANK: union of two partial fetches of the KBW Bank Index (BKX) --
    TradingView (10 names, page login-walled before showing the rest) and
    investing.com (19 names) -- 22 unique tickers after merging. This is
    a "top 20-ish" not a precisely rank-ordered top 20; the union was
    kept as-is rather than force-trimmed to exactly 20, since which two
    marginal regional banks to drop wouldn't materially change scan
    coverage.

OPERATIONAL NOTE: the 2026-08-26 additions above raised the deduplicated
scan universe from 53 symbols to ~198 (post CHRONIC_MOVERS exclusion).

2026-08-28, per explicit user request: added SP500_TOP_200 (S&P 500 top
200 by market cap, see that list's own comment for sourcing/corrections)
to go deeper than the official S&P 100 already in the universe. This
raises the deduplicated scan universe further, to ~247 symbols (post
CHRONIC_MOVERS exclusion) -- about 25% more than before, not the ~2x a
naive +200 might suggest, since most of the S&P top 200 already overlapped
with the existing Dow/Nasdaq/S&P-100/Russell/SOX/KBW lists. Correspondingly
more get_equity_historicals/get_equity_quotes batch calls per live-monitor
cycle (still batched at <=10 symbols each) and a longer cycle runtime --
worth watching the first few live cycles after this change for a
slow/incomplete run, same caveat as the 2026-08-26 expansion.
"""

# Dow Jones Industrial Average: fixed at exactly 30 components.
DOW_JONES_30 = [
    "MMM", "AXP", "AMGN", "AMZN", "AAPL", "BA", "CAT", "CVX", "CSCO", "KO",
    "DIS", "GS", "HD", "HON", "IBM", "JNJ", "JPM", "MCD", "MRK", "MSFT",
    "NKE", "NVDA", "PG", "CRM", "SHW", "TRV", "UNH", "VZ", "V", "WMT",
]

# S&P 500: top 30 constituents by market cap (approximate, mega-cap heavy).
SP500_TOP_30 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK.B", "AVGO", "TSLA",
    "LLY", "JPM", "WMT", "V", "UNH", "XOM", "ORCL", "MA", "HD", "PG", "COST",
    "JNJ", "NFLX", "ABBV", "BAC", "CRM", "KO", "CVX", "MRK", "AMD", "PEP",
]

# NASDAQ: top 30 constituents by market cap (Nasdaq-100 mega caps).
NASDAQ_TOP_30 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "COST",
    "NFLX", "ADBE", "PEP", "AMD", "CSCO", "TMUS", "QCOM", "CMCSA", "TXN",
    "AMAT", "INTU", "ISRG", "BKNG", "HON", "VRTX", "GILD", "ADP", "MU",
    "PANW", "LRCX", "REGN",
]


# Nasdaq-100 (Wikipedia, snapshot dated 2026-01-20 -- 101 tickers incl.
# GOOGL/GOOG dual class). Also satisfies "QQQ top 100" (QQQ tracks this
# index), so that request is not duplicated as a separate list.
NASDAQ_100 = [
    "ADBE", "AMD", "ABNB", "ALNY", "GOOGL", "GOOG", "AMZN", "AEP", "AMGN", "ADI",
    "AAPL", "AMAT", "APP", "ARM", "ASML", "ADSK", "ADP", "AXON", "BKR", "BKNG",
    "AVGO", "CDNS", "CHTR", "CTAS", "CSCO", "CCEP", "CTSH", "CMCSA", "CEG", "CPRT",
    "CSGP", "COST", "CRWD", "CSX", "DDOG", "DXCM", "FANG", "DASH", "EA", "EXC",
    "FAST", "FER", "FTNT", "GEHC", "GILD", "HON", "IDXX", "INSM", "INTC", "INTU",
    "ISRG", "KDP", "KLAC", "KHC", "LRCX", "LIN", "MAR", "MRVL", "MELI", "META",
    "MCHP", "MU", "MSFT", "MSTR", "MDLZ", "MPWR", "MNST", "NFLX", "NVDA", "NXPI",
    "ORLY", "ODFL", "PCAR", "PLTR", "PANW", "PAYX", "PYPL", "PDD", "PEP", "QCOM",
    "REGN", "ROP", "ROST", "SNDK", "STX", "SHOP", "SBUX", "SNPS", "TMUS", "TTWO",
    "TSLA", "TXN", "TRI", "VRSK", "VRTX", "WMT", "WBD", "WDC", "WDAY", "XEL", "ZS",
]

# S&P 100 -- supplied directly by the user 2026-08-26 (their own list, not
# scraped), superseding an earlier WebFetch-derived attempt off the iShares
# OEF ETF holdings CSV. 104 tickers as given (not the commonly-cited "101" --
# used verbatim, not force-trimmed, since this is the user's authoritative
# source). Notable diffs from the scraped OEF-CSV list this replaced: drops
# AMAT, BNY, COF, MU, NOW, PLTR, UBER; adds AIG, BK, CB, CHTR, CME, DOW,
# KMI, MET, PYPL, TGT.
SP_100 = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK.B", "C",
    "CAT", "CB", "CHTR", "CL", "CMCSA", "CME", "COP", "COST", "CRM", "CSCO",
    "CVS", "CVX", "DE", "DHR", "DIS", "DOW", "DUK", "EMR", "FDX", "GD",
    "GE", "GEV", "GILD", "GM", "GOOG", "GOOGL", "GS", "HD", "HON", "IBM",
    "INTC", "INTU", "ISRG", "JNJ", "JPM", "KMI", "KO", "LIN", "LLY", "LMT",
    "LOW", "LRCX", "MA", "MCD", "MDLZ", "MDT", "MET", "META", "MMM", "MO",
    "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NVDA", "ORCL", "PEP", "PFE",
    "PG", "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T",
    "TGT", "TMO", "TMUS", "TSLA", "TXN", "UNH", "UNP", "UPS", "USB", "V",
    "VZ", "WFC", "WMT", "XOM",
]

# Russell Top 100 (iShares IWL "Russell Top 200" holdings CSV, fetched
# 2026-08-26, pre-sorted by weight -- first 100 rows taken; user chose
# Top 100 over Top 200 to sidestep trailing garbled rows in the raw CSV).
RUSSELL_TOP_100 = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "AVGO", "GOOG", "META", "TSLA", "MU",
    "LLY", "JPM", "BRK.B", "AMD", "XOM", "JNJ", "V", "WMT", "INTC", "ABBV",
    "AMAT", "CSCO", "MA", "COST", "BAC", "CAT", "LRCX", "UNH", "CVX", "GE",
    "PG", "HD", "KO", "GS", "MRK", "PLTR", "PM", "GEV", "NFLX", "KLAC",
    "PANW", "WFC", "TXN", "RTX", "MS", "LIN", "SNDK", "C", "ORCL", "AMGN",
    "IBM", "TMO", "APH", "CRWD", "MCD", "ADI", "AXP", "WDC", "PEP", "VZ",
    "NEE", "QCOM", "ANET", "MRVL", "WELL", "UNP", "ABT", "TJX", "DIS", "SCHW",
    "GILD", "BLK", "ETN", "BA", "T", "DE", "COP", "PFE", "CVS", "UBER",
    "PLD", "BKNG", "CRM", "COF", "GLW", "SPGI", "CB", "BMY", "ISRG", "VRTX",
    "MO", "DELL", "PH", "PGR", "SBUX", "VRT", "LOW", "DHR", "HWM", "BNY",
]

# PHLX Semiconductor Sector Index (SOX) top 20 by weight
# (nasdaq.com/docs/SOX factsheet, dated 05/01/2026).
SOX_TOP_20 = [
    "AVGO", "NVDA", "MU", "INTC", "MRVL", "AMD", "TXN", "QCOM", "MPWR", "KLAC",
    "ADI", "LRCX", "NXPI", "TSM", "AMAT", "ASML", "COHR", "TER", "MCHP", "ON",
]

# KBW Bank Index (BKX) -- union of TradingView (10) + investing.com (19)
# partial fetches, 22 unique tickers (see module docstring).
KBW_BANK = [
    "JPM", "BAC", "MS", "GS", "WFC", "C", "COF", "BNY", "PNC", "USB",
    "FITB", "ZION", "NTRS", "HBAN", "TFC", "RF", "STT", "KEY", "MTB", "BK",
    "CBSH", "CFR",
]

# Major index/sector ETFs + leveraged/inverse ETFs (added 2026-08-28 per
# explicit user request). These are the first non-single-stock instruments
# in this universe -- everything above is an individual company; these are
# funds. SPY/QQQ/IWM/DIA track the S&P 500/Nasdaq-100/Russell 2000/Dow
# themselves (diversified, not leveraged); XLF/XLE/XBI/SMH are sector SPDRs
# (financials/energy/biotech/semiconductors). TQQQ/SQQQ/SOXL/LABU are 3x
# daily-leveraged (SQQQ additionally inverse) -- explicitly flagged to the
# user as materially more volatile than anything else in this universe
# (more than the 8 CHRONIC_MOVERS excluded elsewhere for the same reason,
# e.g. TSLA), and added anyway on their explicit confirmation. Worth
# revisiting if these end up dominating signal volume or risk-gate
# rejections once live. One correction from the user's original list: they
# typed "SHM" (a municipal bond ETF, not a fit for an options-volatility
# strategy); confirmed with them this meant SMH (VanEck Semiconductor ETF).
MAJOR_ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XBI", "SMH",
    "TQQQ", "SQQQ", "SOXL", "LABU",
]

# S&P 500 top 200 by market cap (added 2026-08-28 per explicit user request,
# deepening coverage past the official S&P 100 above). Source: slickcharts.com/sp500,
# WebFetched 2026-08-28, which lists all 500 constituents pre-sorted by index
# weight (weight in a cap-weighted index tracks market cap) -- took the first
# 200 rows. One correction made against the raw fetch: row 144 came back as
# "MRSH", not a real ticker -- that's Marsh & McLennan Companies, actual
# ticker MMC, corrected here. LITE (Lumentum, rank ~152) was double-checked
# separately since a recent S&P 500 addition ranking that high is worth
# confirming rather than assuming -- confirmed via Lumentum's own investor
# release and Yahoo Finance coverage of its 2026 index addition and rally.
SP500_TOP_200 = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "AVGO", "META", "TSLA", "BRK.B",
    "LLY", "MU", "JPM", "WMT", "AMD", "V", "JNJ", "XOM", "MA", "INTC",
    "ABBV", "PLTR", "CSCO", "ORCL", "BAC", "COST", "LRCX", "CVX", "KO", "AMAT",
    "CAT", "MRK", "GE", "UNH", "MS", "NFLX", "PG", "HD", "PANW", "GS",
    "DELL", "PM", "RTX", "WFC", "GEV", "ANET", "TXN", "KLAC", "AMGN", "TMO",
    "CRWD", "AXP", "IBM", "LIN", "C", "SNDK", "VZ", "CRM", "MRVL", "APH",
    "ABT", "PEP", "TMUS", "STX", "SCHW", "DIS", "MCD", "GILD", "UNP", "BLK",
    "ADI", "QCOM", "T", "WELL", "NEE", "DE", "BA", "WDC", "ETN", "PFE",
    "UBER", "COP", "BKNG", "DHR", "TJX", "NOW", "NEM", "VRTX", "BMY", "PLD",
    "COF", "LMT", "ISRG", "CB", "GLW", "SPGI", "FTNT", "PGR", "PH", "SYK",
    "SBUX", "CVS", "LOW", "MDT", "ACN", "ADBE", "MO", "ADP", "FCX", "BNY",
    "ABNB", "BX", "HWM", "EQIX", "APP", "GD", "MCK", "VRT", "SO", "MPC",
    "CME", "DASH", "CEG", "TT", "VLO", "KKR", "PNC", "HOOD", "USB", "CSX",
    "CDNS", "PSX", "INTU", "DUK", "CMCSA", "PWR", "MAR", "MMM", "MNST", "HCA",
    "WMB", "ICE", "UPS", "MMC", "SNPS", "EMR", "MCO", "DDOG", "WM", "ELV",
    "JCI", "LITE", "SHW", "REGN", "AMT", "CTAS", "SLB", "ITW", "ECL", "MSI",
    "MDLZ", "APO", "CMI", "FDX", "NOC", "NSC", "TRV", "RCL", "GM", "EOG",
    "TGT", "ROST", "AON", "CI", "HLT", "CL", "WBD", "HPE", "ORLY", "DLR",
    "KMI", "HON", "SPG", "APD", "BSX", "RSG", "AJG", "AEP", "PCAR", "TDG",
    "URI", "ALL", "CRH", "MPWR", "BKR", "GWW", "TFC", "COR", "TRGP", "MET",
]


def get_universe(dedup: bool = True) -> list:
    """Union of all ten lists (the original Dow/S&P-30/Nasdaq-30, the
    2026-08-26 Nasdaq-100/S&P-100/Russell-Top-100/SOX-20/KBW-Bank additions,
    and the 2026-08-28 S&P-500-top-200 + MAJOR_ETFS additions). dedup=True
    (default) collapses overlap -- there's heavy overlap between the
    single-stock lists (mega caps like AAPL/MSFT/NVDA appear in most of
    them), so the deduped universe is meaningfully smaller than the raw
    combined total. MAJOR_ETFS has no overlap with anything else (funds,
    not companies) so all 12 of those always add in full."""
    combined = (
        DOW_JONES_30 + SP500_TOP_30 + NASDAQ_TOP_30
        + NASDAQ_100 + SP_100 + RUSSELL_TOP_100 + SOX_TOP_20 + KBW_BANK
        + SP500_TOP_200 + MAJOR_ETFS
    )
    return sorted(set(combined)) if dedup else combined
