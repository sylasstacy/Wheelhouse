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


def bollinger_bands(hist: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> dict:
    """
    20-day SMA +/- 2 standard deviations. Returns %B (where price sits between
    the bands: 0 = at lower band, 1 = at upper band, can go outside that range
    if price actually breaks through) and band width (as % of price -- a proxy
    for how compressed/expanded volatility currently is).
    """
    close = hist["close"]
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std

    last_close = float(close.iloc[-1])
    last_upper, last_lower = upper.iloc[-1], lower.iloc[-1]

    if pd.isna(last_upper) or pd.isna(last_lower) or (last_upper - last_lower) == 0:
        return {"percent_b": None, "band_width_pct": None, "bb_upper": None, "bb_lower": None}

    percent_b = (last_close - last_lower) / (last_upper - last_lower)
    band_width_pct = (last_upper - last_lower) / last_close * 100

    return {
        "percent_b": round(float(percent_b), 2),
        "band_width_pct": round(float(band_width_pct), 2),
        "bb_upper": round(float(last_upper), 2),
        "bb_lower": round(float(last_lower), 2),
    }


def anchored_vwap(hist: pd.DataFrame, anchor_idx) -> float:
    """VWAP computed from a specific anchor date forward -- the market's
    volume-weighted 'average cost basis' since that point in time."""
    sub = hist.loc[anchor_idx:]
    typical_price = (sub["high"] + sub["low"] + sub["close"]) / 3
    cum_vol = sub["volume"].cumsum()
    if cum_vol.iloc[-1] == 0:
        return float(sub["close"].iloc[-1])
    vwap = (typical_price * sub["volume"]).cumsum() / cum_vol
    return float(vwap.iloc[-1])


def swing_avwaps(hist: pd.DataFrame, lookback: int = 252) -> dict:
    """
    Anchors AVWAP to the two most significant swing points in the lookback
    window: the highest high (captures 'pullback from a recent ATH/major
    high') and the lowest low (captures 'recovery from a major swing low').
    Both are fully dynamic -- no hardcoded event dates, no extra data pull
    beyond what's already fetched.
    """
    window = hist.tail(lookback)
    if len(window) < 10:
        return {}

    last_close = float(hist["close"].iloc[-1])

    high_idx = window["high"].idxmax()
    low_idx = window["low"].idxmin()

    high_avwap = anchored_vwap(hist, high_idx)
    low_avwap = anchored_vwap(hist, low_idx)

    pct_from_high_avwap = (last_close - high_avwap) / high_avwap * 100
    pct_from_low_avwap = (last_close - low_avwap) / low_avwap * 100

    return {
        "swing_high_date": high_idx.strftime("%Y-%m-%d"),
        "swing_high_avwap": round(high_avwap, 2),
        "pct_from_swing_high_avwap": round(pct_from_high_avwap, 1),
        "swing_low_date": low_idx.strftime("%Y-%m-%d"),
        "swing_low_avwap": round(low_avwap, 2),
        "pct_from_swing_low_avwap": round(pct_from_low_avwap, 1),
    }


def trend_score(hist: pd.DataFrame) -> dict:
    """
    Returns a 0-100 base trend score plus diagnostics (MAs, RSI, support
    cushion, Bollinger Bands, anchored VWAP swings). The base score covers
    moving-average position/stacking, support cushion, and AVWAP position --
    RSI and Bollinger %B are interpreted differently depending on strategy
    (e.g. oversold RSI is a caution for LEAPs but an opportunity for CSP
    premium selling), so those are applied on top of this base score in
    scoring.py, not baked in here.
    """
    close = hist["close"]
    last_close = float(close.iloc[-1])
    mas = moving_averages(hist)
    r = rsi(close).iloc[-1]
    bb = bollinger_bands(hist)
    avwap = swing_avwaps(hist)

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

    score = float(np.clip(score, 0, 100))
    dist_to_support_pct = (last_close - support_level(hist)) / last_close * 100

    # Support cushion: reward a healthy buffer above support (room before a normal
    # pullback threatens a short strike), penalize sitting right at/below support
    # (fragile) or being way overextended above it (chasing, due for reversion).
    if dist_to_support_pct < 0:
        score -= 15       # already broken below recent support -- red flag
    elif dist_to_support_pct < 5:
        score -= 5        # very tight cushion, limited margin for error
    elif dist_to_support_pct <= 20:
        score += 8        # sweet spot: comfortable room without being extended
    elif dist_to_support_pct <= 40:
        score += 3        # still fine, more room but less "coiled"
    else:
        score -= 5        # meaningfully extended above support, chasing risk

    # Anchored VWAP (swing high / swing low): price above an anchor's AVWAP
    # means buyers since that reference point are in profit and it tends to
    # act as support; below means the reverse. Modest weight per anchor since
    # this partially overlaps with the moving-average and support checks above.
    def _avwap_bump(pct):
        if pct is None:
            return 0
        if pct >= 15:
            return 6
        elif pct >= 0:
            return 3
        elif pct >= -10:
            return -3
        else:
            return -6

    score += _avwap_bump(avwap.get("pct_from_swing_high_avwap"))
    score += _avwap_bump(avwap.get("pct_from_swing_low_avwap"))

    score = float(np.clip(score, 0, 100))

    return {
        "trend_score": round(score, 1),
        "last_close": round(last_close, 2),
        "sma20": round(mas["sma20"], 2) if not np.isnan(mas["sma20"]) else None,
        "sma50": round(mas["sma50"], 2) if not np.isnan(mas["sma50"]) else None,
        "sma200": round(mas["sma200"], 2) if not np.isnan(mas["sma200"]) else None,
        "rsi": round(float(r), 1) if not np.isnan(r) else None,
        "dist_to_support_pct": round(dist_to_support_pct, 1),
        **bb,
        **avwap,
    }
