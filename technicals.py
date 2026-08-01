"""
Technical scoring: turns raw OHLCV history into a 0-100 "technical score"
used both as a screening input and a scoring sub-factor.

Philosophy for options-selling context:
- For CSPs: want price above rising support, not falling knife
- For LEAPs: want an established, healthy uptrend (higher highs/lows)
- For spreads: trend + momentum inform direction of the structure
"""

from __future__ import annotations
import pandas as pd
import numpy as np


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def moving_averages(hist: pd.DataFrame) -> dict:
    close = hist["close"]
    return {
        "sma20": close.rolling(20).mean().iloc[-1],
        "sma50": close.rolling(50).mean().iloc[-1],
        "sma200": close.rolling(200).mean().iloc[-1] if len(close) >= 200 else np.nan,
    }


def support_level(hist: pd.DataFrame, lookback: int = 60) -> float:
    """Simple support proxy: recent swing low over lookback window."""
    return float(hist["low"].tail(lookback).min())


def trend_score(hist: pd.DataFrame) -> dict:
    """
    Returns a 0-100 trend score plus the underlying diagnostics.
    Blends: price vs moving averages, MA slope/stacking, RSI regime.
    """
    close = hist["close"]
    last_close = float(close.iloc[-1])
    mas = moving_averages(hist)
    r = rsi(close).iloc[-1]

    score = 50.0  # neutral baseline

    # Price above/below key MAs
    if not np.isnan(mas["sma20"]):
        score += 8 if last_close > mas["sma20"] else -8
    if not np.isnan(mas["sma50"]):
        score += 10 if last_close > mas["sma50"] else -10
    if not np.isnan(mas["sma200"]):
        score += 12 if last_close > mas["sma200"] else -12

    # MA stacking (bullish alignment: 20 > 50 > 200)
    if not np.isnan(mas["sma200"]) and mas["sma20"] > mas["sma50"] > mas["sma200"]:
        score += 10
    elif not np.isnan(mas["sma200"]) and mas["sma20"] < mas["sma50"] < mas["sma200"]:
        score -= 10

    # RSI regime: reward healthy momentum, penalize extreme overbought/oversold
    if not np.isnan(r):
        if 45 <= r <= 65:
            score += 8
        elif r > 75:
            score -= 6   # overextended, chase risk for LEAPs
        elif r < 30:
            score -= 6   # downtrend momentum

    score = float(np.clip(score, 0, 100))
    dist_to_support_pct = (last_close - support_level(hist)) / last_close * 100

    return {
        "trend_score": round(score, 1),
        "last_close": round(last_close, 2),
        "sma20": round(mas["sma20"], 2) if not np.isnan(mas["sma20"]) else None,
        "sma50": round(mas["sma50"], 2) if not np.isnan(mas["sma50"]) else None,
        "sma200": round(mas["sma200"], 2) if not np.isnan(mas["sma200"]) else None,
        "rsi": round(float(r), 1) if not np.isnan(r) else None,
        "dist_to_support_pct": round(dist_to_support_pct, 1),
    }
