"""
LEAPS screener - long-dated calls as a stock-replacement / leveraged
directional expression, restricted to names with an established uptrend.
"""

from __future__ import annotations
import datetime as dt
import pandas as pd
from config import SCREEN, bucket_of
from greeks import add_delta_column


def find_leaps_candidates(ticker, snapshot, hist, next_earnings, earnings_status, trend_diag,
                           screen=SCREEN):
    ideas = []
    bucket = bucket_of(ticker)

    if trend_diag["trend_score"] < screen["leaps_min_trend_score"]:
        return ideas  # only pursue LEAPS on names with a real uptrend

    min_dte = screen["leaps_min_dte"]

    for expiry in snapshot.expirations:
        exp_date = dt.datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date - dt.date.today()).days
        if dte < min_dte:
            continue

        calls = snapshot.chains[expiry]["calls"]
        if calls.empty:
            continue
        calls = add_delta_column(calls, snapshot.underlying_price, expiry, "call")

        lo, hi = screen["leaps_target_delta_range"]
        band = calls[(calls["delta"] >= lo) & (calls["delta"] <= hi)]
        if band.empty:
            continue

        for _, row in band.iterrows():
            if row["open_interest"] < screen["min_option_open_interest"]:
                continue
            if pd.isna(row["spread_pct"]) or row["spread_pct"] > screen["max_bid_ask_spread_pct"]:
                continue

            intrinsic = max(snapshot.underlying_price - row["strike"], 0)
            extrinsic = row["mid"] - intrinsic
            extrinsic_pct_of_price = extrinsic / snapshot.underlying_price * 100
            if extrinsic_pct_of_price > screen["leaps_max_extrinsic_pct_of_price"]:
                continue

            breakeven = row["strike"] + row["mid"]
            leverage_ratio = (snapshot.underlying_price / row["mid"]) * row["delta"] if row["mid"] else None

            ideas.append({
                "strategy": "leaps",
                "ticker": ticker,
                "bucket": bucket,
                "expiry": expiry,
                "dte": dte,
                "strike": row["strike"],
                "delta": round(row["delta"], 2),
                "cost_per_contract": round(row["mid"] * 100, 2),
                "intrinsic_value": round(intrinsic, 2),
                "extrinsic_value": round(extrinsic, 2),
                "extrinsic_pct_of_price": round(extrinsic_pct_of_price, 1),
                "breakeven": round(breakeven, 2),
                "leverage_ratio": round(leverage_ratio, 1) if leverage_ratio else None,
                "iv": round(row["iv"] * 100, 1) if pd.notna(row["iv"]) else None,
                "underlying_price": round(snapshot.underlying_price, 2),
                "trend_score": trend_diag["trend_score"],
                "next_earnings": str(next_earnings) if next_earnings else None,
                "earnings_status": earnings_status,
            })

    return ideas
