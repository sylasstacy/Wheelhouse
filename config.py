"""
Central configuration for the options analyst tool.
Edit this file to tune your universe, screening rules, and scoring weights.
Nothing else in the codebase should need to change to adjust your "style."
"""

# ---------------------------------------------------------------------------
# UNIVERSE
# ---------------------------------------------------------------------------
# Organize by bucket so screeners can apply different rules per bucket later
# (e.g. tighter IV/liquidity thresholds on leveraged ETFs).

UNIVERSE = {
    "mega_cap_tech": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO",
        "TSLA", "ORCL", "CRM", "ADBE", "NFLX", "SPCX", "MAGS",
    ],
    "semiconductors": [
        "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "ARM", "TSM", "MRVL", "DRAM", "CBRS", "AMKR", 
        "AKAM", "NVTS", "BOT", "AMBA", "SYNA", "BE", "ENPH", "OKLO", "CRWV", "KEEL", "NBIS", "VIAV", "CIFR",
        "CLSK", "HUT", "IREN", "MARA", "RIOT", "USAR",
    ],
    "software_cloud": [
        "NOW", "PANW", "SNOW", "DDOG", "NET", "CRWD", "MDB", "ZS", "TEAM", "WDAY", "ZETA", "TTD", "RNG", "RDDT"
        "FIVN", "FIG", "PLTR",
    ],
    "consumer_internet_fintech": [
        "SHOP", "UBER", "PYPL", "XYZ", "COIN", "DASH", "RIVN", "HOOD", "SOFI", "COIN", "AFRM", "LMND", "BMNR", 
        "MSTR", "IBIT", "RKLB", "ASTS", "HIMS", "GRAB", "SE",
    ],
    "core_etf": [
        "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "SMH",
    ],
    # Sleeve for expressing leveraged views on sharp drawdowns / rebounds.
    # Screener applies stricter liquidity & IV-crush caution here.
    "leveraged_etf": [
        "TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU", "AAPU", "AMZU", "GGLL", "METU", "TSLL", 
        "PTIR", "ROBN", "HIMZ", "NEBX", "RDTL", "NVDL", "CONL", "ETHU", "MSTX", "BMNU", 
    ],
}

def all_tickers():
    seen = []
    for bucket in UNIVERSE.values():
        for t in bucket:
            if t not in seen:
                seen.append(t)
    return seen

def bucket_of(ticker: str) -> str:
    for bucket, tickers in UNIVERSE.items():
        if ticker in tickers:
            return bucket
    return "unknown"


# ---------------------------------------------------------------------------
# SCREENING RULES
# ---------------------------------------------------------------------------

SCREEN = {
    "min_option_open_interest": 100,        # per-leg OI floor
    "max_bid_ask_spread_pct": 0.12,          # (ask-bid)/mid must be below this
    "min_underlying_avg_dollar_volume": 20_000_000,  # 20-day avg $ volume

    # IV filters
    "min_iv_rank": 25,     # 0-100 scale; below this, premium is usually too thin
    "max_iv_rank_leaps": 60,  # for LEAPs (long vega), don't overpay for IV

    "leveraged_etf_min_iv_rank": 40,  # require more juice to bother in 2x/3x names
    "leveraged_etf_max_dte": 21,      # keep leveraged plays short-dated (decay/path risk)

    # Cash-secured put rules
    "csp_target_delta_range": (0.10, 0.20),   # abs(delta) window -- tightened for lower assignment risk
    "csp_min_dte": 21,
    "csp_max_dte": 45,
    "csp_min_annualized_return_pct": 12.0,    # premium / cash secured, annualized
    "csp_avoid_earnings_within_expiry": True,

    # Credit / debit spread rules
    "spread_target_short_delta_range": (0.20, 0.35),
    "spread_min_dte": 21,
    "spread_max_dte": 60,
    "spread_min_credit_to_width_pct": 25.0,   # credit spreads: credit / width >= this
    "spread_max_width_pct_of_price": 10.0,    # keep strikes reasonably close together

    # LEAPS rules (long-dated directional, typically calls; puts for structural hedges)
    "leaps_min_dte": 270,          # ~9 months+
    "leaps_target_delta_range": (0.65, 0.85),  # deep ITM-ish for stock-replacement feel
    "leaps_max_extrinsic_pct_of_price": 15.0,  # don't overpay time value
    "leaps_min_trend_score": 60,   # require an established uptrend (0-100 scale)
}

# ---------------------------------------------------------------------------
# CSP PREMIUM GRADING
# ---------------------------------------------------------------------------
# The premium sub-score blends two smooth (logistic/S-curve) grades:
#   - raw return on capital (premium / cash secured, NOT annualized) --
#     stops short-dated trades with tiny real payouts from gaming the
#     annualized number
#   - annualized return -- your efficiency/aspirational target
# Each curve is defined by its TARGET: hitting the target scores ~90,
# half the target scores 50, and the curve smoothly (never abruptly)
# approaches 100 well beyond target. No hard caps or breakpoints.

CSP_PREMIUM_RAW_RETURN_TARGET_PCT = 2.0     # "usually looking for" floor
CSP_PREMIUM_ANNUALIZED_TARGET_PCT = 40.0    # "ideally" stretch goal
CSP_PREMIUM_RAW_RETURN_WEIGHT = 0.5         # vs. (1 - this) for annualized

# ---------------------------------------------------------------------------
# CSP RISK GRADING
# ---------------------------------------------------------------------------
# Risk blends three smooth 0-100 sub-factors (weights below), then applies a
# flat leveraged-ETF penalty on top:
#   - cushion: breakeven distance, scaled to THIS TRADE's own expected move
#     (IV x sqrt(DTE/365)) rather than a flat %, so a wide-moving name and a
#     calm one are held to different (fair) absolute cushion bars
#   - liquidity: graduated OI + spread curves with a low floor (not a hard
#     cutoff), plus a same-day-volume bonus that's additive only -- thinly
#     traded names are never gated out, just nudged
#   - volatility: the stock's own realized volatility (magnitude), distinct
#     from the IV-rank timing signal already in the IV category

CSP_RISK_WEIGHTS = {"cushion": 0.40, "liquidity": 0.20, "volatility": 0.40}
CSP_CUSHION_TARGET_MULTIPLIER = 1.25   # target cushion = this x the trade's expected move
CSP_VOLATILITY_RISK_TARGET_PCT = 35.0  # realized vol level where the volatility score bottoms out
CSP_LIQUIDITY_OI_TARGET = 50           # open interest scoring ~90 (down from a flat 300 hard cutoff)
CSP_LIQUIDITY_SPREAD_TARGET_PCT = 6.0  # bid-ask spread % where the liquidity score bottoms out
CSP_LIQUIDITY_VOLUME_BONUS = 5         # flat bump if the contract traded today -- never a penalty if not
CSP_LEVERAGED_ETF_RISK_PENALTY = 15    # same magnitude as before, applied after the blend

# ---------------------------------------------------------------------------
# SCORING WEIGHTS
# ---------------------------------------------------------------------------
# Composite score = weighted sum of 0-100 sub-scores. Weights should sum to 1.0
# per strategy; adjust to match your priorities (e.g. weight IV heavier if
# premium capture matters more to you than trend confirmation).

SCORING_WEIGHTS = {
    "csp": {
        "technicals": 0.25,   # trend strength, distance above support
        "iv": 0.25,           # IV rank / IV vs realized vol
        "premium": 0.25,      # annualized return on cash secured
        "risk": 0.15,         # liquidity, spread width, assignment risk
        "catalyst": 0.10,     # earnings/macro proximity (penalize surprises)
    },
    "spread": {
        "technicals": 0.30,
        "iv": 0.20,
        "premium": 0.20,      # credit/width or debit efficiency
        "risk": 0.20,
        "catalyst": 0.10,
    },
    "leaps": {
        "technicals": 0.35,   # trend matters most for a long-dated directional bet
        "iv": 0.20,           # penalize overpaying extrinsic value
        "premium": 0.15,      # cost efficiency (extrinsic % of price)
        "risk": 0.15,
        "catalyst": 0.15,     # more exposure to catalysts over a long hold
    },
}

# Minimum composite score (0-100) for a trade idea to make the report
MIN_SCORE_TO_REPORT = {
    "csp": 65,
    "spread": 65,
    "leaps": 60,
}

# How many ideas to keep per strategy in the internal ranked lists
MAX_IDEAS_PER_STRATEGY = 8


# ---------------------------------------------------------------------------
# DAILY REPORT COMPOSITION
# ---------------------------------------------------------------------------
# Your report style: CSPs are the core, always show the best 5 that clear
# MIN_SCORE_TO_REPORT["csp"]. Spreads/LEAPs only get added on top when
# they're genuinely exceptional (score >= threshold below) -- not just
# "good enough," since they're opportunistic, not the daily bread and butter.

REPORT_CSP_COUNT = 5
REPORT_EXCEPTIONAL_THRESHOLD = 85   # spreads/LEAPs need this score to make the cut
REPORT_MAX_BONUS_IDEAS = 3          # cap on how many bonus spread/LEAP ideas per day


# ---------------------------------------------------------------------------
# AI THESIS GENERATION
# ---------------------------------------------------------------------------
# Each idea gets a short AI-written thesis via the Claude API (Haiku --
# cheap and plenty capable for this). Requires ANTHROPIC_API_KEY as an
# environment variable / GitHub Actions secret. If it's not set, the
# pipeline automatically falls back to a template-based thesis instead
# of failing, so this is safe to leave on.

THESIS_MODEL = "claude-haiku-4-5-20251001"
THESIS_MAX_TOKENS = 300
