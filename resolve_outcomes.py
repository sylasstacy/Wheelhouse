"""
Checks every logged idea whose expiry has passed, fetches the real closing
price on/near that date, and computes what would have actually happened had
you traded it -- expired worthless, assigned, spread settlement, LEAPS
intrinsic value at expiry.

Run daily, right after report.py, as part of the same GitHub Actions job.
Cheap: only touches ideas that just expired and don't have an outcome yet.
"""

from __future__ import annotations
import json
import pandas as pd

import data_fetch
import storage


def _price_on_or_after(ticker: str, target_date: str):
    """
    Returns the closing price on `target_date`, or the next available trading
    day's close if the target falls on a weekend/holiday (options settle to
    the next trading session's action in that case). Returns None if the
    date is out of range of the pulled history or the ticker fetch fails.
    """
    try:
        hist = data_fetch.get_price_history(ticker, period="1y")
    except Exception:
        return None

    target = pd.Timestamp(target_date)
    idx = hist.index
    on_or_after = hist[idx.tz_localize(None) >= target] if idx.tz is not None \
        else hist[idx >= target]
    if on_or_after.empty:
        return None
    return float(on_or_after["close"].iloc[0])


def _resolve_csp_like(idea: dict, price_at_expiry: float):
    strike = idea["short_strike"]
    premium = idea["premium_per_contract"]
    cash_secured = idea["cash_secured"]
    if price_at_expiry >= strike:
        pnl = premium
        outcome = "expired_otm_full_premium"
    else:
        pnl = premium - (strike - price_at_expiry) * 100
        outcome = "assigned_itm"
    pct_return = pnl / cash_secured * 100 if cash_secured else None
    return outcome, pnl, pct_return


def _resolve_spread(idea: dict, price_at_expiry: float):
    short_strike = idea["short_strike"]
    long_strike = idea["long_strike"]
    credit = idea["credit"]
    width = idea["width"]
    is_put_spread = "put" in idea.get("sub_type", "").lower()

    if is_put_spread:
        # bullish/neutral: max profit above short strike, max loss below long strike
        if price_at_expiry >= short_strike:
            pnl = credit
            outcome = "expired_otm_full_credit"
        elif price_at_expiry <= long_strike:
            pnl = credit - width
            outcome = "max_loss_itm"
        else:
            intrinsic = (short_strike - price_at_expiry) * 100
            pnl = credit - intrinsic
            outcome = "partial_loss"
    else:
        # bearish: max profit below short strike, max loss above long strike
        if price_at_expiry <= short_strike:
            pnl = credit
            outcome = "expired_otm_full_credit"
        elif price_at_expiry >= long_strike:
            pnl = credit - width
            outcome = "max_loss_itm"
        else:
            intrinsic = (price_at_expiry - short_strike) * 100
            pnl = credit - intrinsic
            outcome = "partial_loss"

    pct_return = pnl / width * 100 if width else None
    return outcome, pnl, pct_return


def _resolve_leaps(idea: dict, price_at_expiry: float):
    strike = idea["strike"]
    cost = idea["cost_per_contract"]
    intrinsic_value = max(price_at_expiry - strike, 0) * 100
    pnl = intrinsic_value - cost
    outcome = "itm_at_expiry" if intrinsic_value > 0 else "otm_worthless"
    pct_return = pnl / cost * 100 if cost else None
    return outcome, pnl, pct_return


def resolve_all(verbose: bool = True) -> int:
    unresolved = storage.get_unresolved_expired_ideas()
    resolved_count = 0

    for row in unresolved:
        idea = json.loads(row["idea_json"])
        strategy = row["strategy"]
        ticker = row["ticker"]
        expiry = row["expiry"]

        price = _price_on_or_after(ticker, expiry)
        if price is None:
            if verbose:
                print(f"  {ticker} ({expiry}): couldn't fetch price at/after expiry, skipping for now")
            continue

        try:
            if strategy in ("csp", "leveraged_csp"):
                outcome, pnl, pct_return = _resolve_csp_like(idea, price)
            elif strategy == "spread":
                outcome, pnl, pct_return = _resolve_spread(idea, price)
            elif strategy == "leaps":
                outcome, pnl, pct_return = _resolve_leaps(idea, price)
            else:
                continue
        except Exception as e:
            if verbose:
                print(f"  {ticker} ({expiry}): ERROR resolving outcome - {e}")
            continue

        storage.record_outcome(
            idea_id=row["id"], underlying_price_at_expiry=price,
            outcome=outcome, realized_pnl=round(pnl, 2),
            pct_return_on_capital=round(pct_return, 2) if pct_return is not None else None,
        )
        resolved_count += 1
        if verbose:
            pct_str = f"{pct_return:.1f}%" if pct_return is not None else "n/a"
            print(f"  {ticker} ({strategy}, {expiry}): {outcome}, P&L ${pnl:.2f} ({pct_str})")

    return resolved_count


if __name__ == "__main__":
    print("Resolving expired idea outcomes...")
    n = resolve_all(verbose=True)
    print(f"Resolved {n} idea(s).")
