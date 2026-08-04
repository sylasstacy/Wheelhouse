"""
Generates a static, self-contained HTML dashboard from a pipeline run.
No server needed to VIEW it -- just a webpage. Regenerated daily by an
automated job (see .github/workflows/daily_scan.yml) and published via
GitHub Pages.

Report composition (your style, set in config.py):
  - Core: best REPORT_CSP_COUNT cash-secured puts, excluding leveraged ETFs
  - Leveraged ETF CSPs: best REPORT_LEVERAGED_CSP_COUNT, shown daily as a
    dedicated testing track (not gated behind the exceptional bar)
  - Spreads: best REPORT_SPREAD_COUNT, shown daily as a dedicated testing
    track (not gated behind the exceptional bar)
  - LEAPs: purely opportunistic -- only shown if score >= REPORT_EXCEPTIONAL_THRESHOLD
  - Every idea gets an AI-written thesis (see thesis.py), with a safe
    template fallback if no API key is configured.

Run manually: python report.py
Output: docs/index.html
"""

from __future__ import annotations
import datetime as dt
import os
import pandas as pd
from pipeline import run_pipeline
from config import (
    REPORT_CSP_COUNT,
    REPORT_LEVERAGED_CSP_COUNT,
    REPORT_SPREAD_COUNT,
    REPORT_EXCEPTIONAL_THRESHOLD,
    REPORT_MAX_BONUS_IDEAS,
    MIN_SCORE_TO_REPORT,
)
from thesis import generate_thesis

OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

STRATEGY_LABELS = {
    "csp": "Cash-Secured Put",
    "spread": "Spread",
    "leaps": "LEAPS",
}


def _score_color(score: float) -> str:
    if score >= 80:
        return "#15803d"
    if score >= 65:
        return "#b45309"
    return "#6b7280"


def _select_daily_ideas(results: dict):
    """Returns (core_csps, leveraged_csps, top_spreads, bonus_leaps) per
    your reporting style: core CSPs exclude leveraged ETFs (those get their
    own dedicated track), spreads are shown daily as a testing track, and
    LEAPs stay purely opportunistic (exceptional-only)."""
    csp_df = results["csp"]

    if csp_df.empty:
        core = csp_df
        leveraged_csps = csp_df
    else:
        non_leveraged = csp_df[csp_df["bucket"] != "leveraged_etf"]
        leveraged = csp_df[csp_df["bucket"] == "leveraged_etf"]
        core = non_leveraged.sort_values("composite_score", ascending=False).head(REPORT_CSP_COUNT)
        leveraged_csps = leveraged.sort_values("composite_score", ascending=False).head(REPORT_LEVERAGED_CSP_COUNT)

    spread_df = results["spread"]
    top_spreads = spread_df.sort_values("composite_score", ascending=False).head(REPORT_SPREAD_COUNT) \
        if not spread_df.empty else spread_df

    leaps_df = results["leaps"]
    if leaps_df.empty:
        bonus_leaps = leaps_df
    else:
        exceptional = leaps_df[leaps_df["composite_score"] >= REPORT_EXCEPTIONAL_THRESHOLD]
        bonus_leaps = exceptional.sort_values("composite_score", ascending=False).head(REPORT_MAX_BONUS_IDEAS)

    return core, leveraged_csps, top_spreads, bonus_leaps


def _headline(idea: dict) -> str:
    strategy = idea["strategy"]
    if strategy == "csp":
        return f"Sell {idea['ticker']} ${idea['short_strike']} Put"
    if strategy == "spread":
        return f"{idea['sub_type'].split(' (')[0].title()}: {idea['ticker']} {idea['short_strike']}/{idea['long_strike']}"
    return f"Buy {idea['ticker']} ${idea['strike']} Call (LEAPS)"


def _earnings_display(idea: dict) -> str:
    if idea.get("next_earnings"):
        return idea["next_earnings"]
    if idea.get("earnings_status") == "unavailable":
        return "unconfirmed (data unavailable — check manually)"
    return "none scheduled"


def _technical_rows(idea: dict) -> list:
    """RSI, support cushion, and Bollinger diagnostics -- shown on every card
    for transparency. Band width is informational only (not currently scored)."""
    t = idea.get("trend_diagnostics", {})
    rows = []
    if t.get("rsi") is not None:
        rows.append(("RSI (14d)", t["rsi"]))
    if t.get("dist_to_support_pct") is not None:
        rows.append(("Above Support", f"{t['dist_to_support_pct']:.1f}%"))
    if t.get("percent_b") is not None:
        rows.append(("Bollinger %B", t["percent_b"]))
    if t.get("band_width_pct") is not None:
        rows.append(("Bollinger Band Width", f"{t['band_width_pct']:.1f}%"))
    if t.get("pct_from_swing_high_avwap") is not None:
        rows.append((f"vs Swing-High AVWAP ({t['swing_high_date']})",
                     f"{t['pct_from_swing_high_avwap']:+.1f}%"))
    if t.get("pct_from_swing_low_avwap") is not None:
        rows.append((f"vs Swing-Low AVWAP ({t['swing_low_date']})",
                     f"{t['pct_from_swing_low_avwap']:+.1f}%"))
    return rows


def _detail_rows(idea: dict):
    strategy = idea["strategy"]
    tech_rows = _technical_rows(idea)
    if strategy == "csp":
        return [
            ("Expiry", f"{idea['expiry']} ({idea['dte']}d)"),
            ("Delta", idea["delta"]),
            ("Premium", f"${idea['premium_per_contract']:.2f}"),
            ("Cash Secured", f"${idea['cash_secured']:.2f}"),
            ("Annualized Return", f"{idea['annualized_return_pct']:.1f}%"),
            ("Breakeven", f"${idea['breakeven']:.2f}"),
            ("IV", f"{idea['iv']}%" if idea['iv'] else "n/a"),
            ("Open Interest", idea["open_interest"]),
            *tech_rows,
            ("Next Earnings", _earnings_display(idea)),
        ]
    if strategy == "spread":
        return [
            ("Expiry", f"{idea['expiry']} ({idea['dte']}d)"),
            ("Short Delta", idea["short_delta"]),
            ("Credit", f"${idea['credit']:.2f}"),
            ("Width", f"${idea['width']:.2f}"),
            ("Max Loss", f"${idea['max_loss']:.2f}"),
            ("Max Gain", f"${idea['max_gain']:.2f}"),
            ("Credit/Width", f"{idea['credit_to_width_pct']:.1f}%"),
            *tech_rows,
            ("Next Earnings", _earnings_display(idea)),
        ]
    return [
        ("Expiry", f"{idea['expiry']} ({idea['dte']}d)"),
        ("Delta", idea["delta"]),
        ("Cost/Contract", f"${idea['cost_per_contract']:.2f}"),
        ("Extrinsic % of Price", f"{idea['extrinsic_pct_of_price']:.1f}%"),
        ("Breakeven", f"${idea['breakeven']:.2f}"),
        ("Leverage Ratio", idea["leverage_ratio"]),
        ("Trend Score", idea["trend_score"]),
        *tech_rows,
        ("Next Earnings", _earnings_display(idea)),
    ]


def _idea_card(idea: dict, badge=None) -> str:
    s = idea["scores"]
    color = _score_color(s["composite"])
    thesis_text = generate_thesis(idea)

    rows_html = "".join(
        f'<div class="row"><span class="label">{k}</span><span class="val">{v}</span></div>'
        for k, v in _detail_rows(idea)
    )
    subscores_html = "".join(
        f'<div class="chip">{k}: {v}</div>' for k, v in s.items() if k != "composite"
    )
    badge_html = f'<span class="badge">{badge}</span>' if badge else ""

    return f"""
    <div class="card">
      <div class="card-head">
        <div class="headline">{badge_html}{_headline(idea)}</div>
        <div class="score" style="background:{color}">{s['composite']}</div>
      </div>
      <div class="thesis">{thesis_text}</div>
      <div class="details">{rows_html}</div>
      <div class="chips">{subscores_html}</div>
    </div>
    """


def _section(title: str, df: pd.DataFrame, empty_msg: str, note: str = None, badge_fn=None) -> str:
    if df.empty:
        cards_html = f'<p class="empty">{empty_msg}</p>'
    else:
        cards_html = "".join(
            _idea_card(row.to_dict(), badge=badge_fn(row) if badge_fn else None)
            for _, row in df.iterrows()
        )
    note_html = f'<p class="section-note">{note}</p>' if note else ""
    count = 0 if df.empty else len(df)
    return f"""
    <section>
      <h2>{title} <span class="count">({count})</span></h2>
      {note_html}
      <div class="cards">{cards_html}</div>
    </section>
    """


def generate_report():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = run_pipeline(verbose=True)
    core, leveraged_csps, top_spreads, bonus_leaps = _select_daily_ideas(results)

    now = dt.datetime.now().strftime("%A, %B %d %Y — %I:%M %p")

    core_count = 0 if core.empty else len(core)
    all_frames = [df for df in [core, leveraged_csps, top_spreads, bonus_leaps] if not df.empty]
    total_shown = sum(len(df) for df in all_frames)
    avg_score = round(pd.concat([df["composite_score"] for df in all_frames]).mean(), 1) \
        if all_frames else None

    core_section = _section(
        "Today's Cash-Secured Puts", core,
        "No cash-secured puts cleared the score threshold today."
    )
    leveraged_section = _section(
        "Leveraged ETF CSPs (Testing)", leveraged_csps,
        f"No leveraged ETF CSPs cleared the {MIN_SCORE_TO_REPORT['csp']}+ threshold today.",
        note="Dedicated testing track for your leveraged-ETF CSP sleeve — shown daily, not gated behind an exceptional bar.",
        badge_fn=lambda row: "⚡ Leveraged ETF"
    )
    spread_section = _section(
        "Top Spreads (Testing)", top_spreads,
        f"No spreads cleared the {MIN_SCORE_TO_REPORT['spread']}+ threshold today.",
        note="Dedicated testing track for spreads — shown daily, not gated behind an exceptional bar.",
        badge_fn=lambda row: "📐 Spread"
    )
    bonus_section = _section(
        "Bonus: Exceptional LEAPs", bonus_leaps,
        f"No LEAPs cleared the {REPORT_EXCEPTIONAL_THRESHOLD}+ bar today.",
        note=f"LEAPs that cleared the {REPORT_EXCEPTIONAL_THRESHOLD}+ bar today — purely opportunistic.",
        badge_fn=lambda row: "⭐ LEAPS"
    ) if not bonus_leaps.empty else ""

    stats_html = ""
    if avg_score is not None:
        stats_html = f"""
        <div class="stats">
          <div class="stat"><div class="stat-num">{total_shown}</div><div class="stat-label">Ideas Today</div></div>
          <div class="stat"><div class="stat-num">{avg_score}</div><div class="stat-label">Avg Score</div></div>
          <div class="stat"><div class="stat-num">{core_count}</div><div class="stat-label">Core CSPs</div></div>
          <div class="stat"><div class="stat-num">{0 if leveraged_csps.empty else len(leveraged_csps)}</div><div class="stat-label">Leveraged CSPs</div></div>
          <div class="stat"><div class="stat-num">{0 if top_spreads.empty else len(top_spreads)}</div><div class="stat-label">Spreads</div></div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wheelhouse — Daily Report</title>
<style>
  :root {{
    color-scheme: light;
    --bg: #f4f5f7;
    --ink: #1a1d23;
    --muted: #6b7280;
    --card: #ffffff;
    --border: #e8e9ec;
    --accent: #4f46e5;
    --accent-soft: #eef0ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--ink); margin: 0; padding: 32px 20px;
  }}
  header {{
    max-width: 1100px; margin: 0 auto 20px; display: flex; justify-content: space-between;
    align-items: flex-end; flex-wrap: wrap; gap: 16px;
  }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.02em; }}
  .timestamp {{ color: var(--muted); font-size: 13px; }}
  .stats {{ display: flex; gap: 24px; }}
  .stat {{ text-align: center; }}
  .stat-num {{ font-size: 22px; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .disclaimer {{
    max-width: 1100px; margin: 0 auto 28px; padding: 12px 16px;
    background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px;
    font-size: 12.5px; color: #92610a; line-height: 1.5;
  }}
  main {{ max-width: 1100px; margin: 0 auto; }}
  section {{ margin-bottom: 36px; }}
  h2 {{ font-size: 16px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 2px; }}
  .count {{ color: var(--muted); font-weight: 500; font-size: 13px; }}
  .section-note {{ color: var(--muted); font-size: 12.5px; margin: 4px 0 0; }}
  .empty {{ color: var(--muted); font-style: italic; padding: 20px 0; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; margin-top: 14px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
    padding: 18px; transition: box-shadow 0.15s ease;
  }}
  .card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.06); }}
  .card-head {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 10px; }}
  .headline {{ font-weight: 700; font-size: 15px; line-height: 1.3; }}
  .badge {{
    display: inline-block; background: var(--accent-soft); color: var(--accent);
    border-radius: 6px; padding: 2px 7px; font-size: 10.5px; font-weight: 600;
    margin-bottom: 4px; letter-spacing: 0.02em;
  }}
  .score {{
    color: white; font-weight: 700; font-size: 14px; padding: 5px 12px;
    border-radius: 20px; flex-shrink: 0;
  }}
  .thesis {{
    font-size: 13px; line-height: 1.55; color: #374151; background: #f9fafb;
    border-left: 3px solid var(--accent); padding: 10px 13px; margin-bottom: 14px;
    border-radius: 0 8px 8px 0;
  }}
  .row {{ display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid #f3f4f6; }}
  .row:last-child {{ border-bottom: none; }}
  .label {{ color: var(--muted); }}
  .val {{ font-weight: 600; }}
  .chips {{ margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{ background: #f3f4f6; border-radius: 6px; padding: 3px 9px; font-size: 10.5px; color: #4b5563; font-weight: 500; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>🎡 Wheelhouse</h1>
    <div class="timestamp">Generated {now}</div>
  </div>
  {stats_html}
</header>
<div class="disclaimer">
  Informational only, not investment advice. Greeks are Black-Scholes estimates;
  IV rank is a realized-vol proxy; theses are AI-written from the screened numbers,
  not live news. Verify against your broker before trading.
</div>
<main>
  {core_section}
  {leveraged_section}
  {spread_section}
  {bonus_section}
</main>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"Report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_report()
