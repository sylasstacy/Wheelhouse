"""
Generates a static, self-contained HTML dashboard from a pipeline run.
No server needed to VIEW it -- just a webpage. Regenerated daily by an
automated job (see .github/workflows/daily_scan.yml) and published via
GitHub Pages.

Report composition (your style, set in config.py):
  - Core: best REPORT_CSP_COUNT cash-secured puts, excluding leveraged ETFs
  - Leveraged ETF CSPs: best REPORT_LEVERAGED_CSP_COUNT, shown daily as a
    dedicated testing track
  - Spreads: best REPORT_SPREAD_COUNT, shown daily as a dedicated testing track
  - LEAPs: best REPORT_LEAPS_COUNT, shown daily as a dedicated testing track
  - Every idea gets an AI-written thesis (see thesis.py), with a safe
    template fallback if no API key is configured.

Run manually: python report.py
Output: docs/index.html
"""

from __future__ import annotations
import datetime as dt
import os
from zoneinfo import ZoneInfo
import pandas as pd
from pipeline import run_pipeline
from config import (
    REPORT_CSP_COUNT,
    REPORT_LEVERAGED_CSP_COUNT,
    REPORT_SPREAD_COUNT,
    REPORT_LEAPS_COUNT,
    MIN_SCORE_TO_REPORT,
    LEVERAGED_ETF_PAIRS,
    REPORT_TIMEZONE,
)
from thesis import generate_thesis
from scoring import estimate_annual_decay_pct
import storage

OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

STRATEGY_LABELS = {
    "csp": "Cash-Secured Put",
    "leveraged_csp": "Leveraged ETF CSP",
    "spread": "Spread",
    "leaps": "LEAPS",
}


def _score_color(score: float) -> str:
    if score >= 80:
        return "#15803d"
    if score >= 65:
        return "#b45309"
    return "#6b7280"


def _suppress_weaker_pair(df: pd.DataFrame) -> pd.DataFrame:
    """If both sides of a known inverse pair (TQQQ/SQQQ, etc.) qualify on
    the same day, drop the weaker-scoring half entirely -- the next-best
    non-conflicting idea takes its place instead of just losing a slot."""
    if df.empty:
        return df
    suppressed = set()
    for a, b in LEVERAGED_ETF_PAIRS:
        row_a = df[df["ticker"] == a]
        row_b = df[df["ticker"] == b]
        if not row_a.empty and not row_b.empty:
            score_a = row_a["composite_score"].iloc[0]
            score_b = row_b["composite_score"].iloc[0]
            suppressed.add(a if score_a < score_b else b)
    return df[~df["ticker"].isin(suppressed)]


def _select_daily_ideas(results: dict):
    """Returns (core_csps, leveraged_csps, top_spreads, top_leaps) per your
    reporting style: core CSPs exclude leveraged ETFs entirely (they route
    through their own dedicated strategy/screener), leveraged CSPs/spreads/
    LEAPs are all shown daily as testing tracks."""
    csp_df = results["csp"]
    core = csp_df.sort_values("composite_score", ascending=False).head(REPORT_CSP_COUNT) \
        if not csp_df.empty else csp_df

    leveraged_df = results["leveraged_csp"]
    if leveraged_df.empty:
        leveraged_csps = leveraged_df
    else:
        ranked = leveraged_df.sort_values("composite_score", ascending=False)
        ranked = _suppress_weaker_pair(ranked)
        leveraged_csps = ranked.head(REPORT_LEVERAGED_CSP_COUNT)

    spread_df = results["spread"]
    top_spreads = spread_df.sort_values("composite_score", ascending=False).head(REPORT_SPREAD_COUNT) \
        if not spread_df.empty else spread_df

    leaps_df = results["leaps"]
    top_leaps = leaps_df.sort_values("composite_score", ascending=False).head(REPORT_LEAPS_COUNT) \
        if not leaps_df.empty else leaps_df

    return core, leveraged_csps, top_spreads, top_leaps


def _headline(idea: dict) -> str:
    strategy = idea["strategy"]
    if strategy in ("csp", "leveraged_csp"):
        return f"Sell {idea['ticker']} ${idea['short_strike']} Put"
    if strategy == "spread":
        return f"{idea['sub_type'].split(' (')[0].title()}: {idea['ticker']} {idea['short_strike']}/{idea['long_strike']}"
    return f"Buy {idea['ticker']} ${idea['strike']} Call (LEAPS)"


def _earnings_display(idea: dict) -> str:
    val = idea.get("next_earnings")
    if val and not (isinstance(val, float) and pd.isna(val)):
        return val
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
    if strategy == "leveraged_csp":
        decay_pct = estimate_annual_decay_pct(idea)
        rows = [
            ("Expiry", f"{idea['expiry']} ({idea['dte']}d)"),
            ("Delta", idea["delta"]),
            ("Premium", f"${idea['premium_per_contract']:.2f}"),
            ("Cash Secured", f"${idea['cash_secured']:.2f}"),
            ("Annualized Return", f"{idea['annualized_return_pct']:.1f}%"),
            ("Breakeven", f"${idea['breakeven']:.2f}"),
            ("IV", f"{idea['iv']}%" if idea['iv'] else "n/a"),
            ("Open Interest", idea["open_interest"]),
            ("Leverage", f"{idea.get('leverage_multiplier', 3)}x"),
        ]
        if decay_pct is not None:
            rows.append(("Est. Annual Decay", f"{decay_pct:.1f}%"))
        rows += [*tech_rows, ("Next Earnings", _earnings_display(idea))]
        return rows
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
    price = idea.get("underlying_price")
    price_html = f'<div class="underlying-price">Stock price at scan: ${price:.2f}</div>' if price is not None else ""

    return f"""
    <div class="card">
      <div class="card-head">
        <div class="headline">{badge_html}{_headline(idea)}</div>
        <div class="score" style="background:{color}">{s['composite']}</div>
      </div>
      {price_html}
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
    # GitHub Actions automatically sets GITHUB_EVENT_NAME: "schedule" for the
    # automatic cron run, "workflow_dispatch" for a manually-triggered run
    # (the "Run workflow" button). No workflow YAML changes needed for this.
    github_event = os.environ.get("GITHUB_EVENT_NAME", "")

    # GitHub Actions has had real reliability problems recently -- the
    # workflow fires at three staggered times each morning as backups in
    # case one trigger silently never fires. But if delays stack up, MORE
    # THAN ONE of those triggers can end up actually executing on the same
    # day, each pulling fresh (different, since the market may already be
    # open by then) live data -- overwriting the dashboard with results that
    # don't match whatever got logged as the "official" history entry.
    #
    # Fix: once today's official scheduled run has already succeeded, any
    # LATER scheduled trigger does nothing at all -- no data pull, no report
    # regeneration, dashboard left untouched -- so at most one real analysis
    # ever runs per day and history/dashboard can never diverge. Manual runs
    # (workflow_dispatch) are never affected by this check.
    if github_event == "schedule" and storage.has_scheduled_entry_today():
        print("Today's official scheduled run already completed earlier -- "
              "skipping this redundant backup trigger entirely (no data pulled, "
              "dashboard left as-is).")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = run_pipeline(verbose=True)
    core, leveraged_csps, top_spreads, top_leaps = _select_daily_ideas(results)

    run_type = "scheduled" if github_event == "schedule" else "manual"

    logged = storage.log_daily_ideas({
        "csp": core, "leveraged_csp": leveraged_csps,
        "spread": top_spreads, "leaps": top_leaps,
    }, run_type=run_type)
    print(f"Logged {logged} idea(s) to {storage.DB_PATH} (run_type={run_type})")

    now = dt.datetime.now(ZoneInfo(REPORT_TIMEZONE)).strftime("%A, %B %d %Y — %I:%M %p %Z")

    core_count = 0 if core.empty else len(core)
    all_frames = [df for df in [core, leveraged_csps, top_spreads, top_leaps] if not df.empty]
    total_shown = sum(len(df) for df in all_frames)
    avg_score = round(pd.concat([df["composite_score"] for df in all_frames]).mean(), 1) \
        if all_frames else None

    core_section = _section(
        "Today's Cash-Secured Puts", core,
        "No cash-secured puts cleared the score threshold today."
    )
    leveraged_section = _section(
        "Leveraged ETF CSPs (Testing)", leveraged_csps,
        f"No leveraged ETF CSPs cleared the {MIN_SCORE_TO_REPORT['leveraged_csp']}+ threshold today.",
        note="Dedicated testing track for your leveraged-ETF CSP sleeve — shown daily.",
        badge_fn=lambda row: "⚡ Leveraged ETF"
    )
    spread_section = _section(
        "Top Spreads (Testing)", top_spreads,
        f"No spreads cleared the {MIN_SCORE_TO_REPORT['spread']}+ threshold today.",
        note="Dedicated testing track for spreads — shown daily.",
        badge_fn=lambda row: "📐 Spread"
    )
    leaps_section = _section(
        "Top LEAPs (Testing)", top_leaps,
        f"No LEAPs cleared the {MIN_SCORE_TO_REPORT['leaps']}+ threshold today.",
        note="Dedicated testing track for LEAPs — shown daily.",
        badge_fn=lambda row: "📈 LEAPS"
    )

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
<script>
  (function() {{
    var stored = localStorage.getItem('wheelhouse-theme');
    var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  }})();
</script>
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
    --thesis-bg: #f9fafb;
    --thesis-ink: #374151;
    --chip-bg: #f3f4f6;
    --chip-ink: #4b5563;
    --row-border: #f3f4f6;
    --disclaimer-bg: #fffbeb;
    --disclaimer-border: #fde68a;
    --disclaimer-ink: #92610a;
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --bg: #0f1115;
    --ink: #e5e7eb;
    --muted: #9ca3af;
    --card: #181b21;
    --border: #2a2e37;
    --accent: #818cf8;
    --accent-soft: #262a4a;
    --thesis-bg: #1c1f26;
    --thesis-ink: #d1d5db;
    --chip-bg: #23262e;
    --chip-ink: #b8bcc4;
    --row-border: #262a33;
    --disclaimer-bg: #2a2410;
    --disclaimer-border: #4a3f14;
    --disclaimer-ink: #e8c766;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--ink); margin: 0; padding: 32px 20px;
  }}
  header {{
    max-width: 1320px; margin: 0 auto 20px; display: flex; justify-content: space-between;
    align-items: flex-end; flex-wrap: wrap; gap: 16px;
  }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.02em; }}
  .timestamp {{ color: var(--muted); font-size: 13px; }}
  .header-right {{ display: flex; align-items: center; gap: 20px; }}
  .theme-toggle {{
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 6px 11px; cursor: pointer; font-size: 15px; color: var(--ink); line-height: 1;
  }}
  .theme-toggle:hover {{ border-color: var(--accent); }}
  .stats {{ display: flex; gap: 24px; }}
  .stat {{ text-align: center; }}
  .stat-num {{ font-size: 22px; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .disclaimer {{
    max-width: 1320px; margin: 0 auto 28px; padding: 12px 16px;
    background: var(--disclaimer-bg); border: 1px solid var(--disclaimer-border); border-radius: 10px;
    font-size: 12.5px; color: var(--disclaimer-ink); line-height: 1.5;
  }}
  main {{ max-width: 1320px; margin: 0 auto; }}
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
  .underlying-price {{
    font-size: 12px; color: var(--muted); font-weight: 600; margin-bottom: 10px;
  }}
  .thesis {{
    font-size: 13px; line-height: 1.55; color: var(--thesis-ink); background: var(--thesis-bg);
    border-left: 3px solid var(--accent); padding: 10px 13px; margin-bottom: 14px;
    border-radius: 0 8px 8px 0;
  }}
  .row {{ display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid var(--row-border); }}
  .row:last-child {{ border-bottom: none; }}
  .label {{ color: var(--muted); }}
  .val {{ font-weight: 600; }}
  .chips {{ margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{ background: var(--chip-bg); border-radius: 6px; padding: 3px 9px; font-size: 10.5px; color: var(--chip-ink); font-weight: 500; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>🎡 Wheelhouse</h1>
    <div class="timestamp">Generated {now} · <a href="history.html" style="color:var(--accent);text-decoration:none;font-weight:600;">View history →</a></div>
  </div>
  <div class="header-right">
    {stats_html}
    <button class="theme-toggle" onclick="toggleTheme()" aria-label="Toggle dark mode">🌙</button>
  </div>
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
  {leaps_section}
</main>
<script>
  function toggleTheme() {{
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('wheelhouse-theme', next);
  }}
</script>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"Report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_report()
