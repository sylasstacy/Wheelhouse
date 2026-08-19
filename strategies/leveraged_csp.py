"""
Leveraged ETF Cash-Secured Put screener -- its own dedicated category, not a
sub-case of the core CSP screener. Different DTE window (shorter -- these
aren't meant to be held past ~a month), different delta range (wider/lower --
elevated IV on these products means even far-OTM strikes can carry real
premium), and different scoring downstream (see scoring.py:
score_premium_leveraged_csp, score_risk_leveraged_csp).
"""

from __future__ import annotations
import datetime as dt
import pandas as pd
from config import SCREEN, bucket_of, LEVERAGED_ETF_MULTIPLIER, LEVERAGED_ETF_DEFAULT_MULTIPLIER
from greeks import add_delta_column


def find_leveraged_csp_candidates(ticker, snapshot, hist, next_earnings, earnings_status, screen=SCREEN):
    bucket = bucket_of(ticker)
    if bucket != "leveraged_etf":
        return []  # this screener only runs against the leveraged_etf bucket

    ideas = []
    min_dte = screen["leveraged_csp_min_dte"]
    max_dte = screen["leveraged_csp_max_dte"]
    leverage_multiplier = LEVERAGED_ETF_MULTIPLIER.get(ticker, LEVERAGED_ETF_DEFAULT_MULTIPLIER)

    for expiry in snapshot.expirations:
        exp_date = dt.datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date - dt.date.today()).days
        if not (min_dte <= dte <= max_dte):
            continue

        # earnings avoidance is largely moot for ETFs, but harmless to keep
        if screen["csp_avoid_earnings_within_expiry"] and next_earnings:
            if dt.date.today() <= next_earnings <= exp_date:
                continue

        puts = snapshot.chains[expiry]["puts"]
        if puts.empty:
            continue
        puts = add_delta_column(puts, snapshot.underlying_price, expiry, "put")

        lo, hi = screen["leveraged_csp_target_delta_range"]
        band = puts[(puts["delta"].abs() >= lo) & (puts["delta"].abs() <= hi)]
        if band.empty:
            continue

        for _, row in band.iterrows():
            if row["open_interest"] < screen["min_option_open_interest"]:
                continue
            if pd.isna(row["spread_pct"]) or row["spread_pct"] > screen["max_bid_ask_spread_pct"]:
                continue
            if row["mid"] <= 0:
                continue

            cash_secured = row["strike"] * 100
            premium = row["mid"] * 100
            annualized_return = (premium / cash_secured) * (365 / max(dte, 1)) * 100

            if annualized_return < screen["leveraged_csp_min_annualized_return_pct"]:
                continue

            ideas.append({
                "strategy": "leveraged_csp",
                "ticker": ticker,
                "bucket": bucket,
                "leverage_multiplier": leverage_multiplier,
                "expiry": expiry,
                "dte": dte,
                "short_strike": row["strike"],
                "delta": round(row["delta"], 2),
                "premium_per_contract": round(premium, 2),
                "cash_secured": round(cash_secured, 2),
                "annualized_return_pct": round(annualized_return, 2),
                "breakeven": round(row["strike"] - row["mid"], 2),
                "iv": round(row["iv"] * 100, 1) if pd.notna(row["iv"]) else None,
                "open_interest": int(row["open_interest"]),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
                "bid_ask_spread_pct": round(row["spread_pct"] * 100, 1),
                "underlying_price": round(snapshot.underlying_price, 2),
                "next_earnings": str(next_earnings) if next_earnings else None,
                "earnings_status": earnings_status,
            })

    return ideas
