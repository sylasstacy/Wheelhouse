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
from config import (
    SCORING_WEIGHTS,
    CSP_PREMIUM_RAW_RETURN_TARGET_PCT,
    CSP_PREMIUM_ANNUALIZED_TARGET_PCT,
    CSP_PREMIUM_RAW_RETURN_WEIGHT,
    CSP_RISK_WEIGHTS,
    CSP_CUSHION_TARGET_MULTIPLIER,
    CSP_VOLATILITY_RISK_TARGET_PCT,
    CSP_LIQUIDITY_OI_TARGET,
    CSP_LIQUIDITY_SPREAD_TARGET_PCT,
    CSP_LIQUIDITY_VOLUME_BONUS,
    CSP_LEVERAGED_ETF_RISK_PENALTY,
)


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


def _logistic_target_curve(value: float, target: float) -> float:
    """
    Smooth S-curve with no hard breakpoints: scores ~10 at 0, 50 at half the
    target, ~90 at the target itself, and asymptotically approaches (but
    never quite hits) 100 well beyond it. Every fractional change in `value`
    moves the score -- no flat caps, no sudden cliffs.
    """
    if target <= 0:
        return 50.0
    midpoint = target / 2.0
    k = (2 * np.log(9)) / target   # calibrated so value==target -> score ~90
    score = 100.0 / (1.0 + np.exp(-k * (value - midpoint)))
    return _clip100(score)


def score_premium_csp(idea: dict) -> float:
    raw_return_pct = (idea["premium_per_contract"] / idea["cash_secured"]) * 100
    annualized_pct = idea["annualized_return_pct"]

    raw_score = _logistic_target_curve(raw_return_pct, CSP_PREMIUM_RAW_RETURN_TARGET_PCT)
    ann_score = _logistic_target_curve(annualized_pct, CSP_PREMIUM_ANNUALIZED_TARGET_PCT)

    w = CSP_PREMIUM_RAW_RETURN_WEIGHT
    return _clip100(w * raw_score + (1 - w) * ann_score)


def score_premium_spread(idea: dict) -> float:
    ctw = idea["credit_to_width_pct"]  # credit as % of width
    return _clip100((ctw - 15) / (50 - 15) * 100)


def score_premium_leaps(idea: dict) -> float:
    # lower extrinsic % of price = more capital efficient = higher score
    ext_pct = idea["extrinsic_pct_of_price"]
    return _clip100(100 - (ext_pct / 15 * 100))


def _expected_move_pct(idea: dict) -> float:
    """1-std-dev expected move for THIS trade: IV x sqrt(DTE/365). Falls back
    to a flat 8% if IV is genuinely unavailable, so scoring never breaks."""
    iv_pct = idea.get("iv")
    if iv_pct is None:
        iv_diag = idea.get("iv_diagnostics") or {}
        iv_pct = iv_diag.get("current_atm_iv_pct")
    dte = idea.get("dte")
    if iv_pct is None or not dte:
        return 8.0
    return (iv_pct / 100.0) * np.sqrt(dte / 365.0) * 100.0


def score_risk_csp(idea: dict) -> float:
    # --- Cushion: breakeven distance scaled to this trade's own expected move,
    # so a wide-moving name and a calm one are held to different (fair) bars,
    # instead of one flat % target for every ticker regardless of character.
    raw_cushion_pct = (idea["underlying_price"] - idea["breakeven"]) / idea["underlying_price"] * 100
    cushion_target = _expected_move_pct(idea) * CSP_CUSHION_TARGET_MULTIPLIER
    cushion_score = _logistic_target_curve(raw_cushion_pct, cushion_target)

    # --- Volatility: the stock's own realized vol (magnitude), independent of
    # the IV-rank timing signal already scored in the IV category.
    iv_diag = idea.get("iv_diagnostics") or {}
    realized_vol = iv_diag.get("current_realized_vol_pct")
    if realized_vol is None:
        volatility_score = 50.0
    else:
        volatility_score = 100 - _logistic_target_curve(realized_vol, CSP_VOLATILITY_RISK_TARGET_PCT)

    # --- Liquidity: graduated curves with a low floor (not a hard cutoff), so
    # legitimately thinner names aren't gated out. Same-day volume is a bonus
    # only -- its absence never costs points, since good opportunities in
    # less-traded names don't necessarily trade every single day.
    oi_score = _logistic_target_curve(idea.get("open_interest", 0), CSP_LIQUIDITY_OI_TARGET)
    spread_score = 100 - _logistic_target_curve(idea.get("bid_ask_spread_pct", 0),
                                                 CSP_LIQUIDITY_SPREAD_TARGET_PCT)
    liquidity_score = 0.5 * oi_score + 0.5 * spread_score
    if idea.get("volume", 0) > 0:
        liquidity_score = _clip100(liquidity_score + CSP_LIQUIDITY_VOLUME_BONUS)

    w = CSP_RISK_WEIGHTS
    blended = (
        w["cushion"] * cushion_score
        + w["liquidity"] * liquidity_score
        + w["volatility"] * volatility_score
    )

    if idea.get("bucket") == "leveraged_etf":
        blended -= CSP_LEVERAGED_ETF_RISK_PENALTY

    return _clip100(blended)


def score_risk(idea: dict, strategy: str) -> float:
    if strategy == "csp":
        return score_risk_csp(idea)

    score = 70.0  # baseline
    if strategy == "spread":
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
    """
    Penalize earnings ONLY if they fall inside this specific trade's life
    (today through expiry). If the contract expires before earnings happens,
    there's no post-earnings gap to be exposed to during the trade -- so
    earnings landing after expiry isn't treated as a caution, full stop.
    """
    if not idea.get("next_earnings"):
        # Distinguish "confirmed nothing coming up" from "couldn't confirm" --
        # the latter deserves mild caution, not full confidence.
        if idea.get("earnings_status") == "unavailable":
            return 60.0
        return 85.0
    try:
        earnings_date = dt.datetime.strptime(idea["next_earnings"], "%Y-%m-%d").date()
    except Exception:
        return 70.0
    exp_date = dt.date.today() + dt.timedelta(days=idea[days_to_expiry_field])
    if dt.date.today() <= earnings_date <= exp_date:
        return 20.0  # earnings inside the window = real event risk
    return 85.0  # earnings confirmed, but the trade is done before it happens


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
