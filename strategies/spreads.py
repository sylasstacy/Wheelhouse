"""
Vertical credit spread screener (put credit spreads for bullish/neutral
setups, call credit spreads for bearish/neutral setups).

Logic: find a short leg near the target delta band, then pick the
adjacent further-OTM strike as the long leg to define risk, subject to
a max width (as % of underlying price) and a minimum credit/width ratio.
"""

from __future__ import annotations
import datetime as dt
import pandas as pd
from config import SCREEN, bucket_of
from greeks import add_delta_column


def _build_spread(short_row, long_row, option_type, contract_mult=100):
    credit = (short_row["mid"] - long_row["mid"]) * contract_mult
    width = abs(short_row["strike"] - long_row["strike"]) * contract_mult
    if width <= 0 or credit <= 0:
        return None
    max_loss = width - credit
    max_gain = credit
    credit_to_width_pct = credit / width * 100
    return credit, width, max_loss, max_gain, credit_to_width_pct


def find_spread_candidates(ticker, snapshot, hist, next_earnings, trend_score,
                            screen=SCREEN):
    """
    trend_score: 0-100 technical score, used to decide put-credit (bullish/
    neutral bias, trend_score >= 50) vs call-credit (bearish bias, < 50).
    """
    ideas = []
    bucket = bucket_of(ticker)
    min_dte, max_dte = screen["spread_min_dte"], screen["spread_max_dte"]

    option_type = "put" if trend_score >= 50 else "call"
    direction_label = "bullish/neutral (put credit spread)" if option_type == "put" \
        else "bearish/neutral (call credit spread)"

    for expiry in snapshot.expirations:
        exp_date = dt.datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date - dt.date.today()).days
        if not (min_dte <= dte <= max_dte):
            continue

        chain = snapshot.chains[expiry]["puts" if option_type == "put" else "calls"]
        if chain.empty:
            continue
        chain = add_delta_column(chain, snapshot.underlying_price, expiry, option_type)
        chain = chain.sort_values("strike").reset_index(drop=True)

        lo, hi = screen["spread_target_short_delta_range"]
        short_candidates = chain[(chain["delta"].abs() >= lo) & (chain["delta"].abs() <= hi)]
        if short_candidates.empty:
            continue

        max_width = snapshot.underlying_price * screen["spread_max_width_pct_of_price"] / 100

        for _, short_row in short_candidates.iterrows():
            if short_row["open_interest"] < screen["min_option_open_interest"]:
                continue
            # long leg: next strike further OTM (lower strike for puts, higher for calls)
            strikes = chain["strike"].values
            idx = chain.index[chain["strike"] == short_row["strike"]][0]
            long_idx = idx - 1 if option_type == "put" else idx + 1
            if long_idx < 0 or long_idx >= len(chain):
                continue
            long_row = chain.iloc[long_idx]
            if long_row["open_interest"] < screen["min_option_open_interest"]:
                continue
            if abs(short_row["strike"] - long_row["strike"]) > max_width / 100:
                continue

            result = _build_spread(short_row, long_row, option_type)
            if not result:
                continue
            credit, width, max_loss, max_gain, credit_to_width_pct = result
            if credit_to_width_pct < screen["spread_min_credit_to_width_pct"]:
                continue

            ideas.append({
                "strategy": "spread",
                "sub_type": direction_label,
                "ticker": ticker,
                "bucket": bucket,
                "expiry": expiry,
                "dte": dte,
                "short_strike": short_row["strike"],
                "long_strike": long_row["strike"],
                "short_delta": round(short_row["delta"], 2),
                "credit": round(credit, 2),
                "width": round(width, 2),
                "max_loss": round(max_loss, 2),
                "max_gain": round(max_gain, 2),
                "credit_to_width_pct": round(credit_to_width_pct, 1),
                "iv": round(short_row["iv"] * 100, 1) if pd.notna(short_row["iv"]) else None,
                "underlying_price": round(snapshot.underlying_price, 2),
                "next_earnings": str(next_earnings) if next_earnings else None,
            })

    return ideas
