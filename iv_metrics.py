"""
IV rank / IV percentile calculation.

True IV rank needs a history of daily ATM IV, which most free sources don't
give you directly. We approximate it two ways and blend:

1. Realized-vol-based proxy: compare CURRENT ATM implied vol to the stock's
   own trailing realized vol distribution (cheap, robust, no extra data).
2. If you upgrade to Tradier/ORATS later, swap in true historical IV rank
   via `set_true_iv_history()` -- the rest of the code doesn't need to change.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def realized_vol(hist: pd.DataFrame, window: int = 20) -> pd.Series:
    log_ret = np.log(hist["close"] / hist["close"].shift(1))
    return log_ret.rolling(window).std() * np.sqrt(252) * 100  # annualized %


def atm_implied_vol(snapshot, expiry: str) -> float | None:
    """Grabs IV of the option closest to ATM for a given expiry."""
    chain = snapshot.chains.get(expiry)
    if not chain:
        return None
    calls = chain["calls"]
    if calls.empty:
        return None
    idx = (calls["strike"] - snapshot.underlying_price).abs().idxmin()
    iv = calls.loc[idx, "iv"]
    return float(iv) * 100 if pd.notna(iv) else None


def iv_rank_proxy(hist: pd.DataFrame, current_atm_iv_pct: float, window: int = 252) -> dict:
    """
    Approximates IV rank by placing current ATM IV against the trailing
    distribution of 20-day realized vol (a reasonable stand-in when true
    historical IV series isn't available).

    Returns 0-100 rank plus diagnostics.
    """
    rv = realized_vol(hist, window=20).dropna().tail(window)
    if rv.empty or current_atm_iv_pct is None:
        return {"iv_rank": None, "iv_vs_rv_pct": None, "rv_low": None, "rv_high": None}

    rv_low, rv_high = float(rv.min()), float(rv.max())
    if rv_high == rv_low:
        rank = 50.0
    else:
        rank = (current_atm_iv_pct - rv_low) / (rv_high - rv_low) * 100
        rank = float(np.clip(rank, 0, 100))

    current_rv = float(rv.iloc[-1])
    iv_vs_rv_pct = (current_atm_iv_pct - current_rv) / current_rv * 100 if current_rv else None

    return {
        "iv_rank": round(rank, 1),
        "current_atm_iv_pct": round(current_atm_iv_pct, 1),
        "current_realized_vol_pct": round(current_rv, 1),
        "iv_vs_rv_pct": round(iv_vs_rv_pct, 1) if iv_vs_rv_pct is not None else None,
        "rv_range_1y": (round(rv_low, 1), round(rv_high, 1)),
    }
