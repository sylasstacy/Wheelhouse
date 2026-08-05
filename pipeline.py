"""
Orchestrates the full daily run:
  1. For each ticker: pull price history + options snapshot + earnings date
  2. Compute technicals + IV metrics
  3. Run each strategy screener
  4. Score every resulting idea
  5. Filter by MIN_SCORE_TO_REPORT, sort, cap at MAX_IDEAS_PER_STRATEGY
  6. Return a tidy results dict ready for the dashboard / report

Run standalone: `python pipeline.py` prints a summary to console.
Import `run_pipeline()` from dashboard.py for the interactive version.
"""

from __future__ import annotations
import sys
import datetime as dt
import traceback
import pandas as pd

from config import (
    all_tickers, SCREEN, MIN_SCORE_TO_REPORT, MAX_IDEAS_PER_STRATEGY,
    EARNINGS_POST_REPORT_BUFFER_DAYS,
)
import data_fetch
import technicals
import iv_metrics
from strategies.csp import find_csp_candidates
from strategies.leveraged_csp import find_leveraged_csp_candidates
from strategies.spreads import find_spread_candidates
from strategies.leaps import find_leaps_candidates
from scoring import score_idea


def analyze_ticker(ticker: str, verbose: bool = False) -> list[dict]:
    """Returns a list of scored trade ideas across all strategies for one ticker."""
    ideas = []
    try:
        hist = data_fetch.get_price_history(ticker)
        avg_dollar_vol = data_fetch.get_avg_dollar_volume(hist)
        if avg_dollar_vol < SCREEN["min_underlying_avg_dollar_volume"]:
            if verbose:
                print(f"  {ticker}: skipped, avg dollar volume too low")
            return []

        trend_diag = technicals.trend_score(hist)
        snapshot = data_fetch.get_options_snapshot(ticker)
        if not snapshot.expirations:
            if verbose:
                print(f"  {ticker}: no options chain available")
            return []

        next_earnings, earnings_status = data_fetch.get_next_earnings_date(ticker)
        recent_earnings = data_fetch.get_recent_earnings_date(ticker)

        if recent_earnings:
            days_since = (dt.date.today() - recent_earnings).days
            if 0 <= days_since <= EARNINGS_POST_REPORT_BUFFER_DAYS:
                if verbose:
                    print(f"  {ticker}: skipped, reported earnings {recent_earnings} "
                          f"(within the {EARNINGS_POST_REPORT_BUFFER_DAYS}-day post-report buffer)")
                return []

        # IV metrics off the nearest ~30-45 DTE expiration as a representative read
        rep_expiry = snapshot.expirations[min(2, len(snapshot.expirations) - 1)]
        atm_iv = iv_metrics.atm_implied_vol(snapshot, rep_expiry)
        iv_rank_data = iv_metrics.iv_rank_proxy(hist, atm_iv)

        raw_ideas = []
        raw_ideas += find_csp_candidates(ticker, snapshot, hist, next_earnings, earnings_status)
        raw_ideas += find_leveraged_csp_candidates(ticker, snapshot, hist, next_earnings, earnings_status)
        raw_ideas += find_spread_candidates(ticker, snapshot, hist, next_earnings, earnings_status,
                                             trend_diag["trend_score"], verbose=verbose)
        raw_ideas += find_leaps_candidates(ticker, snapshot, hist, next_earnings, earnings_status, trend_diag)

        for idea in raw_ideas:
            idea["trend_diagnostics"] = trend_diag
            idea["iv_diagnostics"] = iv_rank_data
            idea["recent_earnings_date"] = str(recent_earnings) if recent_earnings else None
            scored = score_idea(idea, trend_diag, iv_rank_data)
            ideas.append(scored)

        if verbose:
            print(f"  {ticker}: {len(ideas)} raw ideas generated")

    except Exception as e:
        if verbose:
            print(f"  {ticker}: ERROR - {e}")
            traceback.print_exc()
        return []

    return ideas


def _dedupe_best_per_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Keeps only the highest-scoring idea per ticker within a strategy, so
    one name with several attractive strikes/expiries doesn't crowd out
    diversification across the report."""
    if df.empty:
        return df
    best_idx = df.groupby("ticker")["composite_score"].idxmax()
    return df.loc[best_idx]


def run_pipeline(tickers=None, verbose=True) -> dict:
    tickers = tickers or all_tickers()
    all_ideas = []

    for i, ticker in enumerate(tickers, 1):
        if verbose:
            print(f"[{i}/{len(tickers)}] Analyzing {ticker}...")
        all_ideas += analyze_ticker(ticker, verbose=verbose)

    df = pd.DataFrame(all_ideas)
    if df.empty:
        return {"csp": df, "leveraged_csp": df, "spread": df, "leaps": df, "all": df}

    # pandas turns None into float NaN when building a DataFrame from a list
    # of dicts -- and NaN is truthy in Python, unlike None, which broke every
    # "if idea.get('next_earnings')" check downstream (displayed the literal
    # string "nan" instead of the intended fallback text). Cast to plain
    # object dtype first -- pandas' newer default string dtype silently
    # discards a bare None and reverts to its own NaN marker otherwise.
    for col in ("next_earnings", "recent_earnings_date"):
        if col in df.columns:
            df[col] = df[col].astype(object).where(df[col].notna(), None)

    df["composite_score"] = df["scores"].apply(lambda s: s["composite"])

    results = {}
    for strategy in ["csp", "leveraged_csp", "spread", "leaps"]:
        sub = df[df["strategy"] == strategy].copy()
        min_score = MIN_SCORE_TO_REPORT[strategy]
        sub = sub[sub["composite_score"] >= min_score]
        sub = _dedupe_best_per_ticker(sub)
        sub = sub.sort_values("composite_score", ascending=False)
        sub = sub.head(MAX_IDEAS_PER_STRATEGY * 3)  # keep extra headroom; dashboard can re-cap
        results[strategy] = sub

    results["all"] = df
    return results


if __name__ == "__main__":
    verbose = "--quiet" not in sys.argv
    results = run_pipeline(verbose=verbose)
    for strategy in ["csp", "leveraged_csp", "spread", "leaps"]:
        sub = results[strategy]
        print(f"\n=== {strategy.upper()} — {len(sub)} ideas above threshold ===")
        if not sub.empty:
            cols = ["ticker", "expiry", "dte", "composite_score"]
            print(sub[cols].to_string(index=False))
