"""
Generates a natural-language thesis for each trade idea using the Claude API
(Haiku -- cheap, fast, plenty capable for a structured writeup like this).

Requires ANTHROPIC_API_KEY as an environment variable (set as a GitHub
Actions secret in production: Settings -> Secrets and variables -> Actions).
If no key is present, or the API call fails for any reason, this falls back
to a deterministic template-based thesis so the daily report never breaks.
"""

from __future__ import annotations
import os
import pandas as pd
from config import THESIS_MODEL, THESIS_MAX_TOKENS, LEVERAGED_ETF_DEFAULT_MULTIPLIER
from scoring import estimate_annual_decay_pct

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

_client = None


def _get_client():
    global _client
    if _client is None and Anthropic is not None and os.environ.get("ANTHROPIC_API_KEY"):
        _client = Anthropic()
    return _client


def _template_thesis(idea: dict) -> str:
    """Deterministic fallback -- used if no API key is set or a call fails."""
    strategy = idea["strategy"]
    s = idea["scores"]
    if strategy == "csp":
        return (
            f"{idea['ticker']} trades at ${idea['underlying_price']}. Selling the "
            f"${idea['short_strike']} put ({idea['delta']} delta, {idea['dte']}d to expiry) "
            f"collects ${idea['premium_per_contract']:.2f} in premium, a "
            f"{idea['annualized_return_pct']:.1f}% annualized return on "
            f"${idea['cash_secured']:.2f} secured. Composite score {s['composite']}/100 "
            f"(technicals {s['technicals']}, IV {s['iv']}, premium {s['premium']})."
        )
    if strategy == "leveraged_csp":
        decay_pct = estimate_annual_decay_pct(idea)
        decay_note = f", est. {decay_pct:.1f}% annual decay drag" if decay_pct is not None else ""
        return (
            f"{idea['ticker']} ({idea.get('leverage_multiplier', LEVERAGED_ETF_DEFAULT_MULTIPLIER)}x leveraged) trades at "
            f"${idea['underlying_price']}. Selling the ${idea['short_strike']} put "
            f"({idea['delta']} delta, {idea['dte']}d to expiry) collects "
            f"${idea['premium_per_contract']:.2f} in premium, a {idea['annualized_return_pct']:.1f}% "
            f"annualized return on ${idea['cash_secured']:.2f} secured{decay_note}. "
            f"Composite score {s['composite']}/100 (technicals {s['technicals']}, IV {s['iv']}, "
            f"premium {s['premium']}, risk {s['risk']})."
        )
    if strategy == "spread":
        return (
            f"{idea['ticker']}'s {idea['sub_type']} at {idea['short_strike']}/{idea['long_strike']} "
            f"({idea['dte']}d) collects ${idea['credit']:.2f} credit against ${idea['width']:.2f} "
            f"width ({idea['credit_to_width_pct']:.1f}% of max risk). Composite score "
            f"{s['composite']}/100, cleared the exceptional-opportunity bar for spreads today."
        )
    return (
        f"{idea['ticker']}'s trend score of {idea['trend_score']} supports the long-dated "
        f"${idea['strike']} call ({idea['delta']} delta, {idea['dte']}d), costing "
        f"${idea['cost_per_contract']:.2f} with extrinsic value at "
        f"{idea['extrinsic_pct_of_price']:.1f}% of the stock price. Composite score "
        f"{s['composite']}/100, cleared the exceptional-opportunity bar for LEAPs today."
    )


def _build_prompt(idea: dict) -> str:
    strategy = idea["strategy"]
    s = idea["scores"]
    trend = idea.get("trend_diagnostics", {})
    iv = idea.get("iv_diagnostics", {})

    next_earnings = idea.get("next_earnings")
    if isinstance(next_earnings, float) and pd.isna(next_earnings):
        next_earnings = None
    base_facts = (
        f"Strategy: {strategy}\n"
        f"Ticker: {idea['ticker']} (universe bucket: {idea['bucket']})\n"
        f"Underlying price: ${idea['underlying_price']}\n"
        f"Expiry: {idea['expiry']} ({idea['dte']} days out)\n"
        f"Composite score: {s['composite']}/100 "
        f"(technicals {s['technicals']}, IV {s['iv']}, premium {s['premium']}, "
        f"risk {s['risk']}, catalyst {s['catalyst']})\n"
        f"Trend diagnostics: {trend}\n"
        f"IV diagnostics: {iv}\n"
        f"Next earnings: {next_earnings or ('unconfirmed/unavailable, not a confirmed absence' if idea.get('earnings_status') == 'unavailable' else 'none scheduled')}\n"
    )

    if strategy == "csp":
        structure = (
            f"Structure: sell the ${idea['short_strike']} put, {idea['delta']} delta, "
            f"collecting ${idea['premium_per_contract']:.2f} premium on "
            f"${idea['cash_secured']:.2f} cash secured "
            f"({idea['annualized_return_pct']:.1f}% annualized). Breakeven ${idea['breakeven']:.2f}."
        )
    elif strategy == "leveraged_csp":
        decay_pct = estimate_annual_decay_pct(idea)
        decay_line = f" Estimated annual volatility-decay drag: {decay_pct:.1f}%." if decay_pct is not None else ""
        structure = (
            f"Structure: sell the ${idea['short_strike']} put on a "
            f"{idea.get('leverage_multiplier', LEVERAGED_ETF_DEFAULT_MULTIPLIER)}x leveraged ETF, {idea['delta']} delta, "
            f"collecting ${idea['premium_per_contract']:.2f} premium on "
            f"${idea['cash_secured']:.2f} cash secured "
            f"({idea['annualized_return_pct']:.1f}% annualized). Breakeven ${idea['breakeven']:.2f}."
            f"{decay_line}"
        )
    elif strategy == "spread":
        structure = (
            f"Structure: {idea['sub_type']}, short {idea['short_strike']} / long {idea['long_strike']}, "
            f"credit ${idea['credit']:.2f} on ${idea['width']:.2f} width "
            f"({idea['credit_to_width_pct']:.1f}% of max risk). "
            f"Max loss ${idea['max_loss']:.2f}, max gain ${idea['max_gain']:.2f}."
        )
    else:
        structure = (
            f"Structure: buy the ${idea['strike']} call, {idea['delta']} delta, {idea['dte']} DTE, "
            f"costing ${idea['cost_per_contract']:.2f} "
            f"(extrinsic value {idea['extrinsic_pct_of_price']:.1f}% of stock price). "
            f"Breakeven ${idea['breakeven']:.2f}."
        )

    return (
        "You are writing a concise, specific investment thesis for an options trade idea, "
        "for an experienced retail options trader who already knows options mechanics. "
        "Use ONLY the data provided below -- never invent news, catalysts, or facts not listed. "
        "Write 3-5 sentences covering: (1) why this setup screened well, tied to the specific "
        "numbers given, (2) the main risk to watch, (3) what would invalidate the thesis. "
        "Be direct and specific with numbers, not generic filler. No preamble, no disclaimers, "
        "no markdown formatting -- just the thesis paragraph.\n\n"
        f"{base_facts}\n{structure}"
    )


def generate_thesis(idea: dict) -> str:
    client = _get_client()
    if client is None:
        return _template_thesis(idea)

    try:
        response = client.messages.create(
            model=THESIS_MODEL,
            max_tokens=THESIS_MAX_TOKENS,
            messages=[{"role": "user", "content": _build_prompt(idea)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text.strip() or _template_thesis(idea)
    except Exception:
        # Never let a flaky API call break the daily report.
        return _template_thesis(idea)
