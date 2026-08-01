"""
Generates a static, self-contained HTML dashboard from a pipeline run.
No server needed to VIEW it -- just a webpage. Regenerated daily by an
automated job (see .github/workflows/daily_scan.yml) and published via
GitHub Pages.

Report composition (your style, set in config.py):
  - Always shows the best REPORT_CSP_COUNT cash-secured puts that clear
    the CSP score threshold -- this is the daily core.
  - Spreads/LEAPs are opportunistic: only added if they score at or above
    REPORT_EXCEPTIONAL_THRESHOLD, capped at REPORT_MAX_BONUS_IDEAS.
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
from config import REPORT_CSP_COUNT, REPORT_EXCEPTIONAL_THRESHOLD, REPORT_MAX_BONUS_IDEAS
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
    """Returns (core_csps, bonus_ideas) per your reporting style."""
    csp_df = results["csp"]
    core = csp_df.sort_values("composite_score", ascending=False).head(REPORT_CSP_COUNT) \
        if not csp_df.empty else csp_df

    bonus_frames = []
    for strategy in ["spread", "leaps"]:
        sub = results[strategy]
        if sub.empty:
            continue
        exceptional = sub[sub["composite_score"] >= REPORT_EXCEPTIONAL_THRESHOLD]
        bonus_frames.append(exceptional)

    if bonus_frames:
        bonus = pd.concat(bonus_frames)
        bonus = bonus.sort_values("composite_score", ascending=False).head(REPORT_MAX_BONUS_IDEAS)
    else:
        bonus = pd.DataFrame()

    return core, bonus


def _headline(idea: dict) -> str:
    strategy = idea["strategy"]
    if strategy == "csp":
        return f"Sell {idea['ticker']} ${idea['short_strike']} Put"
    if strategy == "spread":
        return f"{idea['sub_type'].split(' (')[0].title()}: {idea['ticker']} {idea['short_strike']}/{idea['long_strike']}"
    return f"Buy {idea['ticker']} ${idea['strike']} Call (LEAPS)"


def _detail_rows(idea: dict):
    strategy = idea["strategy"]
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
            ("Next Earnings", idea["next_earnings"] or "none scheduled"),
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
            ("Next Earnings", idea["next_earnings"] or "none scheduled"),
        ]
    return [
        ("Expiry", f"{idea['expiry']} ({idea['dte']}d)"),
        ("Delta", idea["delta"]),
        ("Cost/Contract", f"${idea['cost_per_contract']:.2f}"),
        ("Extrinsic % of Price", f"{idea['extrinsic_pct_of_price']:.1f}%"),
        ("Breakeven", f"${idea['breakeven']:.2f}"),
        ("Leverage Ratio", idea["leverage_ratio"]),
        ("Trend Score", idea["trend_score"]),
        ("Next Earnings", idea["next_earnings"] or "none scheduled"),
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


def generate_report():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = run_pipeline(verbose=True)
    core, bonus = _select_daily_ideas(results)

    now = dt.datetime.now().strftime("%A, %B %d %Y — %I:%M %p")

    if core.empty:
        core_html = '<p class="empty">No cash-secured puts cleared the score threshold today.</p>'
        core_count = 0
    else:
        core_html = "".join(_idea_card(row.to_dict()) for _, row in core.iterrows())
        core_count = len(core)

    total_shown = core_count + (0 if bonus.empty else len(bonus))
    avg_score = None
    if not core.empty or not bonus.empty:
        all_scores = pd.concat([
            core["composite_score"] if not core.empty else pd.Series(dtype=float),
            bonus["composite_score"] if not bonus.empty else pd.Series(dtype=float),
        ])
        avg_score = round(all_scores.mean(), 1) if not all_scores.empty else None

    if bonus.empty:
        bonus_section = ""
    else:
        bonus_cards = "".join(
            _idea_card(row.to_dict(), badge=f"⭐ {STRATEGY_LABELS[row['strategy']]}")
            for _, row in bonus.iterrows()
        )
        bonus_section = f"""
        <section>
          <h2>Bonus: Exceptional Opportunities <span class="count">({len(bonus)})</span></h2>
          <p class="section-note">Spreads/LEAPs that cleared the {REPORT_EXCEPTIONAL_THRESHOLD}+ bar today.</p>
          <div class="cards">{bonus_cards}</div>
        </section>
        """

    stats_html = ""
    if avg_score is not None:
        stats_html = f"""
        <div class="stats">
          <div class="stat"><div class="stat-num">{total_shown}</div><div class="stat-label">Ideas Today</div></div>
          <div class="stat"><div class="stat-num">{avg_score}</div><div class="stat-label">Avg Score</div></div>
          <div class="stat"><div class="stat-num">{core_count}</div><div class="stat-label">Core CSPs</div></div>
          <div class="stat"><div class="stat-num">{0 if bonus.empty else len(bonus)}</div><div class="stat-label">Bonus Ideas</div></div>
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
  <section>
    <h2>Today's Cash-Secured Puts <span class="count">({core_count})</span></h2>
    <div class="cards">{core_html}</div>
  </section>
  {bonus_section}
</main>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"Report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_report()
