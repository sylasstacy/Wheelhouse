"""
Data access layer. Everything downstream (screeners, scoring, dashboard)
talks to THIS module, never directly to yfinance. That means swapping in
Tradier/Polygon/ORATS later is a rewrite of this file only.

Functions return plain pandas DataFrames / dicts with consistent column
names regardless of backend.
"""

from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    yf = None  # allows the rest of the code to be imported/tested without it


# ---------------------------------------------------------------------------
# Underlying price history
# ---------------------------------------------------------------------------

def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Returns OHLCV history with a DatetimeIndex."""
    if yf is None:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")
    t = yf.Ticker(ticker)
    hist = t.history(period=period, interval=interval, auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No price history returned for {ticker}")
    hist = hist.rename(columns=str.lower)
    return hist[["open", "high", "low", "close", "volume"]]


def get_avg_dollar_volume(hist: pd.DataFrame, window: int = 20) -> float:
    dollar_vol = hist["close"] * hist["volume"]
    return float(dollar_vol.tail(window).mean())


# ---------------------------------------------------------------------------
# Options chain
# ---------------------------------------------------------------------------

@dataclass
class OptionsSnapshot:
    ticker: str
    underlying_price: float
    expirations: list = field(default_factory=list)
    chains: dict = field(default_factory=dict)  # expiry -> {"calls": df, "puts": df}


def get_options_snapshot(ticker: str, max_expirations: int = 12) -> OptionsSnapshot:
    """
    Pulls the options chain for a ticker across available expirations.
    yfinance option_chain() gives: strike, lastPrice, bid, ask, volume,
    openInterest, impliedVolatility, inTheMoney, contractSymbol.
    Delta/theta/gamma are NOT provided by yfinance -> we estimate delta
    via Black-Scholes in `greeks.py` since it's needed for strike selection.
    """
    if yf is None:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    t = yf.Ticker(ticker)
    price = t.fast_info.get("lastPrice") or t.history(period="1d")["Close"].iloc[-1]

    exps = list(t.options)[:max_expirations]
    chains = {}
    for exp in exps:
        try:
            oc = t.option_chain(exp)
            calls = _clean_chain(oc.calls)
            puts = _clean_chain(oc.puts)
            chains[exp] = {"calls": calls, "puts": puts}
        except Exception:
            continue

    return OptionsSnapshot(ticker=ticker, underlying_price=float(price),
                            expirations=list(chains.keys()), chains=chains)


def _clean_chain(df: pd.DataFrame) -> pd.DataFrame:
    cols = {
        "strike": "strike", "lastPrice": "last_price", "bid": "bid", "ask": "ask",
        "volume": "volume", "openInterest": "open_interest",
        "impliedVolatility": "iv", "inTheMoney": "itm", "contractSymbol": "symbol",
    }
    out = df.rename(columns=cols)[list(cols.values())].copy()
    out["mid"] = (out["bid"] + out["ask"]) / 2
    # guard against zero-mid rows (illiquid/stale quotes)
    out["spread_pct"] = np.where(
        out["mid"] > 0, (out["ask"] - out["bid"]) / out["mid"], np.nan
    )
    return out


# ---------------------------------------------------------------------------
# Earnings / catalyst calendar
# ---------------------------------------------------------------------------

def get_next_earnings_date(ticker: str) -> dt.date | None:
    if yf is None:
        return None
    try:
        t = yf.Ticker(ticker)
        cal = t.get_earnings_dates(limit=4)
        if cal is None or cal.empty:
            return None
        future = cal[cal.index >= pd.Timestamp.now(tz=cal.index.tz)]
        if future.empty:
            return None
        return future.index[0].date()
    except Exception:
        return None
