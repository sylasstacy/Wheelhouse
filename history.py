"""
Generates docs/history.html from wheelhouse.db -- a browsable log of every
past recommendation and, once resolved, what actually happened.

Run manually: python history.py
Output: docs/history.html
"""

from __future__ import annotations
import os
import storage

OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "history.html")

STRATEGY_LABELS = {
    "csp": "CSP", "leveraged_csp": "Leveraged CSP",
    "spread": "Spread", "leaps": "LEAPS",
}

OUTCOME_COLORS = {
    "expired_otm_full_premium": "#15803d", "expired_otm_full_credit": "#15803d",
    "itm_at_expiry": "#15803d",
    "assigned_itm": "#b45309", "partial_loss": "#b45309",
    "max_loss_itm": "#b91c1c", "otm_worthless": "#b91c1c",
}


def _row_html(row: dict) -> str:
    outcome = row.get("outcome")
    if outcome:
        pnl = row.get("realized_pnl")
        pct = row.get("pct_return_on_capital")
        color = OUTCOME_COLORS.get(outcome, "#6b7280")
        pnl_str = f"${pnl:,.2f}" if pnl is not None else "n/a"
        pct_str = f"{pct:+.1f}%" if pct is not None else ""
        outcome_html = f'<span class="outcome" style="color:{color}">{outcome.replace("_", " ")}</span>' \
                        f'<div class="pnl">{pnl_str} {pct_str}</div>'
    else:
        outcome_html = '<span class="pending">pending (not yet expired)</span>'

    return f"""
    <tr>
      <td>{row['scan_date']}</td>
      <td>{STRATEGY_LABELS.get(row['strategy'], row['strategy'])}</td>
      <td class="ticker">{row['ticker']}</td>
      <td>#{row['rank_in_section']}</td>
      <td>{row['composite_score']}</td>
      <td>{row['expiry'] or '—'}</td>
      <td>{outcome_html}</td>
    </tr>
    """


def generate_history(limit_days: int = 60):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    rows = storage.fetch_history(limit_days=limit_days)

    resolved = [r for r in rows if r.get("outcome")]
    wins = [r for r in resolved if r.get("realized_pnl", 0) and r["realized_pnl"] > 0]
    win_rate = round(len(wins) / len(resolved) * 100, 1) if resolved else None

    stats_html = ""
    if rows:
        stats_html = f"""
        <div class="stats">
          <div class="stat"><div class="stat-num">{len(rows)}</div><div class="stat-label">Ideas Logged</div></div>
          <div class="stat"><div class="stat-num">{len(resolved)}</div><div class="stat-label">Resolved</div></div>
          <div class="stat"><div class="stat-num">{win_rate if win_rate is not None else '—'}{'%' if win_rate is not None else ''}</div><div class="stat-label">Win Rate</div></div>
        </div>
        """

    table_rows = "".join(_row_html(r) for r in rows) if rows else \
        '<tr><td colspan="7" class="empty">No history yet -- check back after a few daily scans.</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wheelhouse — History</title>
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
    --bg: #f4f5f7; --ink: #1a1d23; --muted: #6b7280; --card: #ffffff;
    --border: #e8e9ec; --accent: #4f46e5; --row-hover: #f9fafb;
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --bg: #0f1115; --ink: #e5e7eb; --muted: #9ca3af; --card: #181b21;
    --border: #2a2e37; --accent: #818cf8; --row-hover: #1c1f26;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--ink); margin: 0; padding: 32px 20px;
  }}
  header {{ max-width: 1100px; margin: 0 auto 20px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.02em; }}
  .subtitle {{ color: var(--muted); font-size: 13px; }}
  .nav-link {{ color: var(--accent); text-decoration: none; font-size: 13px; font-weight: 600; }}
  .stats {{ display: flex; gap: 24px; }}
  .stat {{ text-align: center; }}
  .stat-num {{ font-size: 22px; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  main {{ max-width: 1100px; margin: 0 auto; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  th {{ text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 10px 14px; border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--border); }}
  tr:hover td {{ background: var(--row-hover); }}
  tr:last-child td {{ border-bottom: none; }}
  .ticker {{ font-weight: 700; }}
  .outcome {{ font-weight: 600; text-transform: capitalize; }}
  .pnl {{ font-size: 11px; color: var(--muted); }}
  .pending {{ color: var(--muted); font-style: italic; }}
  .empty {{ text-align: center; color: var(--muted); font-style: italic; padding: 30px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>🎡 Wheelhouse — History</h1>
    <div class="subtitle">Every idea shown in the last {limit_days} days · <a class="nav-link" href="index.html">← Back to today's report</a></div>
  </div>
  {stats_html}
</header>
<main>
  <table>
    <thead>
      <tr><th>Date</th><th>Strategy</th><th>Ticker</th><th>Rank</th><th>Score</th><th>Expiry</th><th>Outcome</th></tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</main>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"History written to {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_history()
