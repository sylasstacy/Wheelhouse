"""
Cash-Secured Put screener.

For each ticker: pull chain, filter expirations to the target DTE window,
find puts near the target delta band, apply liquidity/premium filters,
and emit structured trade-idea dicts ready for scoring.
"""

from __future__ import annotations
import datetime as dt
import pandas as pd
from config import SCREEN, bucket_of
from greeks import add_delta_column, years_to_expiry


def find_csp_candidates(ticker, snapshot, hist, next_earnings, screen=SCREEN):
    ideas = []
    bucket = bucket_of(ticker)
    min_dte, max_dte = screen["csp_min_dte"], screen["csp_max_dte"]
    if bucket == "leveraged_etf":
        max_dte = min(max_dte, screen["leveraged_etf_max_dte"])

    for expiry in snapshot.expirations:
        exp_date = dt.datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date - dt.date.today()).days
        if not (min_dte <= dte <= max_dte):
            continue

        # avoid earnings inside the expiration window if configured
        if screen["csp_avoid_earnings_within_expiry"] and next_earnings:
            if dt.date.today() <= next_earnings <= exp_date:
                continue

        puts = snapshot.chains[expiry]["puts"]
        if puts.empty:
            continue
        puts = add_delta_column(puts, snapshot.underlying_price, expiry, "put")

        lo, hi = screen["csp_target_delta_range"]
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

            if annualized_return < screen["csp_min_annualized_return_pct"]:
                continue

            ideas.append({
                "strategy": "csp",
                "ticker": ticker,
                "bucket": bucket,
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
                "bid_ask_spread_pct": round(row["spread_pct"] * 100, 1),
                "underlying_price": round(snapshot.underlying_price, 2),
                "next_earnings": str(next_earnings) if next_earnings else None,
            })

    return ideas
