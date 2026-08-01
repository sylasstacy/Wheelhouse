"""
Black-Scholes delta/theta estimation.

yfinance option chains give us IV but not greeks, so we compute delta
ourselves to do strike selection (e.g. "sell the ~25-delta put").
Good enough for screening purposes; not meant to replace a broker's
real-time greeks for execution.
"""

from __future__ import annotations
import numpy as np
from scipy.stats import norm

RISK_FREE_RATE = 0.045  # update periodically, or wire to a live source


def bs_delta(S: float, K: float, T: float, sigma: float, option_type: str,
             r: float = RISK_FREE_RATE) -> float:
    """
    S: underlying price, K: strike, T: years to expiry,
    sigma: implied vol (decimal, e.g. 0.30), option_type: 'call' or 'put'
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    if option_type == "call":
        return float(norm.cdf(d1))
    elif option_type == "put":
        return float(norm.cdf(d1) - 1)
    raise ValueError("option_type must be 'call' or 'put'")


def years_to_expiry(expiry_str: str) -> float:
    import datetime as dt
    exp = dt.datetime.strptime(expiry_str, "%Y-%m-%d").date()
    days = (exp - dt.date.today()).days
    return max(days, 0) / 365.0


def add_delta_column(chain_df, underlying_price: float, expiry_str: str, option_type: str):
    T = years_to_expiry(expiry_str)
    chain_df = chain_df.copy()
    chain_df["dte"] = int(T * 365)
    chain_df["delta"] = chain_df.apply(
        lambda row: bs_delta(underlying_price, row["strike"], T, row["iv"], option_type),
        axis=1,
    )
    return chain_df
