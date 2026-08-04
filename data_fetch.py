"""
Data access layer. Everything downstream (screeners, scoring, dashboard)
talks to THIS module, never directly to yfinance. That means swapping in
Tradier/Polygon/ORATS later is a rewrite of this file only.

Functions return plain pandas DataFrames / dicts with consistent column
names regardless of backend.
"""

from __future__ import annotations
import datetime as dt
import os
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
import requests

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

def get_next_earnings_date(ticker: str):
    """
    Returns (date_or_None, status) where status is one of:
      'confirmed'   - either a specific upcoming earnings date was found, OR
                       the source responded successfully with nothing upcoming
                       (a genuine confirmed-clean result, not a guess)
      'unavailable' - the fetch itself failed or wasn't configured; genuinely
                       unknown, NOT the same as "confirmed no earnings"

    Tries Finnhub first (purpose-built earnings calendar, needs FINNHUB_API_KEY),
    falls back to yfinance's calendar scrape only if Finnhub isn't configured
    or its request fails -- so this works with zero setup, and gets more
    reliable once FINNHUB_API_KEY is added.
    """
    date, status = _get_next_earnings_date_finnhub(ticker)
    if status == "confirmed":
        return date, status
    return _get_next_earnings_date_yfinance(ticker)


def _get_next_earnings_date_finnhub(ticker: str):
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return None, "unavailable"
    try:
        today = dt.date.today()
        horizon = today + dt.timedelta(days=120)  # comfortably covers all screening DTE windows
        url = (
            "https://finnhub.io/api/v1/calendar/earnings"
            f"?symbol={ticker}&from={today.isoformat()}&to={horizon.isoformat()}&token={api_key}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("earningsCalendar", [])
        dates = sorted(e["date"] for e in events if e.get("date"))
        if not dates:
            return None, "confirmed"   # Finnhub responded successfully with nothing upcoming
        next_date = dt.datetime.strptime(dates[0], "%Y-%m-%d").date()
        return next_date, "confirmed"
    except Exception:
        return None, "unavailable"


def _get_next_earnings_date_yfinance(ticker: str):
    if yf is None:
        return None, "unavailable"
    try:
        t = yf.Ticker(ticker)
        cal = t.get_earnings_dates(limit=4)
        if cal is None or cal.empty:
            return None, "unavailable"
        future = cal[cal.index >= pd.Timestamp.now(tz=cal.index.tz)]
        if future.empty:
            return None, "unavailable"
        return future.index[0].date(), "confirmed"
    except Exception:
        return None, "unavailable"
