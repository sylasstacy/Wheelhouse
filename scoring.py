"""
Composite scoring engine. Turns each raw trade idea (from strategies/*.py)
into 0-100 sub-scores for technicals / IV / premium / risk / catalyst, then
a single weighted composite score using config.SCORING_WEIGHTS.

Sub-scores are intentionally simple and transparent (linear mappings /
clear thresholds) so you can audit *why* something scored well and tune
config.py rather than fight a black box.
"""

from __future__ import annotations
import datetime as dt
import numpy as np
from config import SCORING_WEIGHTS


def _clip100(x):
    return float(np.clip(x, 0, 100))


def score_technicals(trend_diag: dict, strategy: str) -> float:
    base = trend_diag["trend_score"]
    if strategy == "spread" and base < 50:
        # bearish spread: invert so a strong downtrend also scores well
        base = 100 - base

    # RSI regime -- interpretation depends on strategy. For CSPs (premium
    # selling), oversold is an opportunity: richer premium from fear, and
    # mean-reversion odds favor the seller -- provided the rest of the score
    # (MA position, support cushion) already confirms this isn't a falling
    # knife, which it independently does. For LEAPs/spreads, oversold stays
    # a caution since you're taking on long-dated directional exposure.
    rsi = trend_diag.get("rsi")
    if rsi is not None:
        if strategy == "csp":
            if rsi < 30:
                base += 8       # oversold = opportunity for premium selling
            elif 45 <= rsi <= 65:
                base += 8       # healthy, steady momentum
            elif rsi > 75:
                base -= 6       # overbought / chasing
        else:
            if 45 <= rsi <= 65:
                base += 8
            elif rsi > 75:
                base -= 6
            elif rsi < 30:
                base -= 6       # oversold still a caution for LEAPs/spreads

    # Bollinger %B -- CSP-only for now, lightly weighted since it's
    # correlated with RSI (both measure "how stretched is this move").
    # Keeping the magnitude modest avoids double-counting the same read.
    if strategy == "csp":
        percent_b = trend_diag.get("percent_b")
        if percent_b is not None:
            if percent_b < 0:
                base += 5       # trading below the lower band -- opportunity
            elif percent_b > 1:
                base -= 4       # trading above the upper band -- mild caution

    return _clip100(base)


def score_iv(iv_metrics: dict, strategy: str) -> float:
    rank = iv_metrics.get("iv_rank")
    if rank is None:
        return 50.0
    if strategy == "leaps":
        # for LEAPS (buying vega), LOWER iv rank is better - invert
        return _clip100(100 - rank)
    # for premium-selling strategies, higher IV rank = more attractive premium
    return _clip100(rank)


def score_premium_csp(idea: dict) -> float:
    # map annualized return of 8% -> 30, 15% -> 65, 25%+ -> 100 (rough linear-ish curve)
    ar = idea["annualized_return_pct"]
    return _clip100((ar - 5) / (30 - 5) * 100)


def score_premium_spread(idea: dict) -> float:
    ctw = idea["credit_to_width_pct"]  # credit as % of width
    return _clip100((ctw - 15) / (50 - 15) * 100)


def score_premium_leaps(idea: dict) -> float:
    # lower extrinsic % of price = more capital efficient = higher score
    ext_pct = idea["extrinsic_pct_of_price"]
    return _clip100(100 - (ext_pct / 15 * 100))


def score_risk(idea: dict, strategy: str) -> float:
    score = 70.0  # baseline
    if strategy == "csp":
        if idea["open_interest"] < 300:
            score -= 10
        if idea["bid_ask_spread_pct"] > 8:
            score -= 10
        if idea["bucket"] == "leveraged_etf":
            score -= 15  # inherent path-dependency/decay risk
    elif strategy == "spread":
        # defined risk is inherently safer than naked exposure
        score += 10
        if idea["bucket"] == "leveraged_etf":
            score -= 10
    elif strategy == "leaps":
        if idea["bucket"] == "leveraged_etf":
            score -= 20  # long-dated leveraged ETF options decay badly; discourage
        if idea["dte"] < 365:
            score -= 5
    return _clip100(score)


def score_catalyst(idea: dict, days_to_expiry_field="dte") -> float:
    """Penalize proximity to earnings/binary catalysts inside the trade window."""
    if not idea.get("next_earnings"):
        # Distinguish "confirmed nothing coming up" from "couldn't confirm" --
        # the latter deserves mild caution, not full confidence.
        if idea.get("earnings_status") == "unavailable":
            return 60.0
        return 80.0
    try:
        earnings_date = dt.datetime.strptime(idea["next_earnings"], "%Y-%m-%d").date()
    except Exception:
        return 70.0
    exp_date = dt.date.today() + dt.timedelta(days=idea[days_to_expiry_field])
    if dt.date.today() <= earnings_date <= exp_date:
        return 20.0  # earnings inside the window = real event risk
    days_out = (earnings_date - dt.date.today()).days
    if 0 <= days_out <= 10:
        return 50.0  # earnings soon after expiry — still worth flagging
    return 85.0


def score_idea(idea: dict, trend_diag: dict, iv_metrics: dict) -> dict:
    strategy = idea["strategy"]
    weights = SCORING_WEIGHTS[strategy]

    technicals = score_technicals(trend_diag, strategy)
    iv = score_iv(iv_metrics, strategy)
    risk = score_risk(idea, strategy)
    catalyst = score_catalyst(idea)

    if strategy == "csp":
        premium = score_premium_csp(idea)
    elif strategy == "spread":
        premium = score_premium_spread(idea)
    else:
        premium = score_premium_leaps(idea)

    composite = (
        technicals * weights["technicals"]
        + iv * weights["iv"]
        + premium * weights["premium"]
        + risk * weights["risk"]
        + catalyst * weights["catalyst"]
    )

    idea["scores"] = {
        "technicals": round(technicals, 1),
        "iv": round(iv, 1),
        "premium": round(premium, 1),
        "risk": round(risk, 1),
        "catalyst": round(catalyst, 1),
        "composite": round(composite, 1),
    }
    return idea
