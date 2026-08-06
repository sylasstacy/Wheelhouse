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
        "NOW", "PANW", "SNOW", "DDOG", "NET", "CRWD", "MDB", "ZS", "TEAM", "WDAY", "ZETA", "TTD", "RNG", "RDDT",
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
        "PTIR", "ROBN", "HIMZ", "NEBX", "RDTL", "NVDL", "CONL", "ETHU", "MSTX", "BMNU", "MUU", "AMDL",
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


# Leverage multiplier per leveraged-ETF ticker (used for the volatility-decay
# estimate). Defaults to 3 for anything not listed -- update this if you add
# 2x products (e.g. SSO/SDS) or anything else with a different multiplier.
LEVERAGED_ETF_MULTIPLIER = {
    "TQQQ": 3, "SQQQ": 3, "SOXL": 3, "SOXS": 3,
    "SPXL": 3, "SPXS": 3, "UPRO": 3, "SPXU": 3,
}

# Inverse pairs -- if both sides of a pair qualify for the leveraged CSP
# testing track on the same day, the weaker-scoring half is auto-suppressed
# (see report.py). Update this list if your leveraged bucket's tickers change.
LEVERAGED_ETF_PAIRS = [
    ("TQQQ", "SQQQ"),
    ("SOXL", "SOXS"),
    ("SPXL", "SPXS"),
    ("UPRO", "SPXU"),
]


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

    # Cash-secured put rules
    "csp_target_delta_range": (0.10, 0.20),   # abs(delta) window -- tightened for lower assignment risk
    "csp_min_dte": 21,
    "csp_max_dte": 45,
    "csp_min_annualized_return_pct": 12.0,    # premium / cash secured, annualized
    "csp_avoid_earnings_within_expiry": True,

    # Leveraged ETF CSPs -- own category, own rules. Shorter DTE (you don't
    # want to hold these past ~a month), wider/lower delta (elevated IV on
    # these products means even far-OTM strikes can carry real premium).
    "leveraged_csp_target_delta_range": (0.02, 0.20),
    "leveraged_csp_min_dte": 7,
    "leveraged_csp_max_dte": 35,
    "leveraged_csp_min_annualized_return_pct": 5.0,   # lower floor -- far-OTM plays are meant to be thin

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
# LEVERAGED ETF CSP PREMIUM GRADING
# ---------------------------------------------------------------------------
# Same smooth curve shape as core CSP premium grading, recalibrated for this
# category's actual trade profile: the 0.02-0.20 delta range intentionally
# includes far-OTM, deliberately thin-premium trades, so the raw-return
# target is lower (don't punish appropriately conservative plays) while the
# annualized target is higher (these products' elevated IV supports richer
# annualized figures even off modest raw premium).

LEVERAGED_CSP_PREMIUM_RAW_RETURN_TARGET_PCT = 1.5
LEVERAGED_CSP_PREMIUM_ANNUALIZED_TARGET_PCT = 50.0
LEVERAGED_CSP_PREMIUM_RAW_RETURN_WEIGHT = 0.5


# ---------------------------------------------------------------------------
# CSP RISK GRADING
# ---------------------------------------------------------------------------
# Risk blends three smooth 0-100 sub-factors:
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


# ---------------------------------------------------------------------------
# LEVERAGED ETF CSP RISK GRADING
# ---------------------------------------------------------------------------
# Risk blends three smooth 0-100 sub-factors:
#   - decay: estimated annual volatility-decay drag from daily-reset leveraged
#     compounding (0.5 x (L-1)/L x realized_vol^2) -- derived from data already
#     fetched, no new data source needed. This REPLACES a standalone realized-
#     vol factor rather than stacking alongside it, since decay is a strictly
#     more informative transformation of the same underlying number.
#   - cushion: same expected-move-scaled logic as core CSP (reused directly)
#   - liquidity: same graduated OI/spread/volume logic as core CSP (reused)
# No separate flat leveraged-ETF penalty -- decay now captures that
# structural risk directly and precisely instead of a blunt flat deduction.

LEVERAGED_CSP_RISK_WEIGHTS = {"decay": 0.45, "cushion": 0.35, "liquidity": 0.20}
LEVERAGED_CSP_DECAY_TARGET_PCT = 15.0  # estimated annual decay % where the decay score bottoms out


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
    "leveraged_csp": {
        "technicals": 0.20,
        "iv": 0.20,
        "premium": 0.30,      # "purely for premium generation" -- leads alongside risk
        "risk": 0.30,         # leverage means downside math matters as much as premium
        "catalyst": 0.0,      # ETFs don't have single-company earnings -- non-factor
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
    "leveraged_csp": 55,   # small 8-ticker pool + tighter DTE window = fewer candidates;
                            # set lower deliberately while this is a testing track
    "spread": 65,
    "leaps": 60,
}

# How many ideas to keep per strategy in the internal ranked lists
MAX_IDEAS_PER_STRATEGY = 8

# Treat earnings within this many days AGO as still-live event risk (day-of
# the report + the following session) -- catches "just reported, still
# digesting the move" risk that a forward-only earnings check can't see.
EARNINGS_POST_REPORT_BUFFER_DAYS = 1


# ---------------------------------------------------------------------------
# DAILY REPORT COMPOSITION
# ---------------------------------------------------------------------------
# Your report style: CSPs are the core, always show the best 5 (non-leveraged
# names) that clear MIN_SCORE_TO_REPORT["csp"]. LEAPs stay purely opportunistic
# -- only added when genuinely exceptional (score >= threshold below).
#
# Two dedicated testing tracks, shown daily regardless of the exceptional
# bar, so you can build a track record on strategies you're evaluating:
#   - leveraged ETF CSPs: their own dedicated strategy/screener entirely
#   - spreads: shown daily rather than gated behind the exceptional bar

REPORT_CSP_COUNT = 5
REPORT_LEVERAGED_CSP_COUNT = 2   # top leveraged-ETF CSPs shown daily (testing track)
REPORT_SPREAD_COUNT = 2          # top spreads shown daily (testing track)
REPORT_LEAPS_COUNT = 2           # top LEAPs shown daily (testing track)


# ---------------------------------------------------------------------------
# TIMEZONE
# ---------------------------------------------------------------------------
# GitHub Actions runners default to UTC, not your local time -- this makes
# sure the "Generated" timestamp on the report always shows your actual
# local time regardless of what timezone the server happens to be running
# in. Update if you ever move: any IANA timezone name works (e.g.
# "America/New_York", "America/Los_Angeles", "Europe/London").

REPORT_TIMEZONE = "America/Chicago"

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
