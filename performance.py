"""
Generates docs/performance.html -- aggregate performance analytics across
every resolved (expired) recommendation:
  - CSP/Leveraged CSP outcomes (worthless vs. assigned) broken down by score
    bucket, so you can see whether higher scores actually predict better
    real-world outcomes
  - Results by strategy: win rate, total realized P&L, average return,
    premium/credit collected vs. capital at risk (adapted per strategy,
    since CSPs/leveraged CSPs use cash-secured collateral, spreads use
    width, LEAPs use cost basis -- these aren't directly comparable, so
    they're kept as separate totals rather than one blended number)
  - Score validation: average composite score of winners vs. losers

Only counts the official scheduled record (same reasoning as history.html)
so manual test scans never skew the numbers.

Run manually: python performance.py
Output: docs/performance.html
"""

from __future__ import annotations
import json
import os
import storage

OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "performance.html")

CSP_STRATEGIES = ("csp", "leveraged_csp")
STRATEGY_LABELS = {
    "csp": "Cash-Secured Put", "leveraged_csp": "Leveraged ETF CSP",
    "spread": "Spread", "leaps": "LEAPS",
}

BUCKET_ORDER = ["80-100", "70-79", "60-69", "Below 60", "Unknown"]


def _score_bucket(score) -> str:
    if score is None:
        return "Unknown"
    if score >= 80:
        return "80-100"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "Below 60"


def _load_resolved():
    rows = storage.fetch_resolved(run_type="scheduled")
    for r in rows:
        try:
            r["idea"] = json.loads(r["idea_json"])
        except Exception:
            r["idea"] = {}
    return rows


def _csp_bucket_breakdown(rows):
    """Worthless vs. assigned counts, by score bucket, for CSP-like strategies."""
    buckets = {b: {"worthless": 0, "assigned": 0} for b in BUCKET_ORDER}
    for r in rows:
        if r["strategy"] not in CSP_STRATEGIES:
            continue
        bucket = _score_bucket(r["composite_score"])
        if r["outcome"] == "expired_otm_full_premium":
            buckets[bucket]["worthless"] += 1
        elif r["outcome"] == "assigned_itm":
            buckets[bucket]["assigned"] += 1
    return buckets


def _strategy_performance(rows):
    perf = {}
    for strategy in ("csp", "leveraged_csp", "spread", "leaps"):
        sub = [r for r in rows if r["strategy"] == strategy]
        if not sub:
            continue
        wins = [r for r in sub if (r["realized_pnl"] or 0) > 0]
        total_pnl = sum(r["realized_pnl"] or 0 for r in sub)
        returns = [r["pct_return_on_capital"] for r in sub if r["pct_return_on_capital"] is not None]
        avg_return = sum(returns) / len(returns) if returns else None

        total_premium = 0.0
        total_collateral = 0.0
        for r in sub:
            idea = r["idea"]
            if strategy in CSP_STRATEGIES:
                total_premium += idea.get("premium_per_contract") or 0
                total_collateral += idea.get("cash_secured") or 0
            elif strategy == "spread":
                total_premium += idea.get("credit") or 0
                total_collateral += idea.get("width") or 0
            elif strategy == "leaps":
                total_collateral += idea.get("cost_per_contract") or 0

        perf[strategy] = {
            "count": len(sub),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(sub) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_return_pct": round(avg_return, 2) if avg_return is not None else None,
            "total_premium": round(total_premium, 2),
            "total_collateral": round(total_collateral, 2),
        }
    return perf


def _score_validation(rows):
    """Average composite score of winners vs. losers -- does the score
    actually predict the outcome, or not?"""
    wins = [r["composite_score"] for r in rows if (r["realized_pnl"] or 0) > 0 and r["composite_score"] is not None]
    losses = [r["composite_score"] for r in rows if (r["realized_pnl"] or 0) <= 0 and r["composite_score"] is not None]
    return {
        "avg_score_winners": round(sum(wins) / len(wins), 1) if wins else None,
        "avg_score_losers": round(sum(losses) / len(losses), 1) if losses else None,
        "n_winners": len(wins),
        "n_losers": len(losses),
    }


def _bucket_table_html(buckets) -> str:
    rows_html = ""
    for b in BUCKET_ORDER:
        w, a = buckets[b]["worthless"], buckets[b]["assigned"]
        total = w + a
        if total == 0:
            continue
        win_rate = round(w / total * 100, 1)
        rows_html += f"""
        <tr>
          <td class="bucket">{b}</td>
          <td>{w}</td>
          <td>{a}</td>
          <td>{total}</td>
          <td class="winrate">{win_rate}%</td>
        </tr>
        """
    if not rows_html:
        return '<p class="empty">No resolved CSP/leveraged CSP trades yet.</p>'
    return f"""
    <table>
      <thead><tr><th>Score Bucket</th><th>Expired Worthless</th><th>Assigned</th><th>Total</th><th>Win Rate</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """


def _strategy_table_html(perf) -> str:
    rows_html = ""
    for strategy, p in perf.items():
        label = STRATEGY_LABELS.get(strategy, strategy)
        premium_label = "Cost Basis" if strategy == "leaps" else ("Credit" if strategy == "spread" else "Premium")
        collateral_label = "Max Risk" if strategy == "spread" else ("Cost Basis" if strategy == "leaps" else "Collateral")
        pnl_color = "#15803d" if p["total_pnl"] >= 0 else "#b91c1c"
        rows_html += f"""
        <tr>
          <td class="strat">{label}</td>
          <td>{p['count']}</td>
          <td>{p['win_rate']}%</td>
          <td style="color:{pnl_color}">${p['total_pnl']:,.2f}</td>
          <td>{f"{p['avg_return_pct']:+.1f}%" if p['avg_return_pct'] is not None else 'n/a'}</td>
          <td>{premium_label}: ${p['total_premium']:,.2f}</td>
          <td>{collateral_label}: ${p['total_collateral']:,.2f}</td>
        </tr>
        """
    if not rows_html:
        return '<p class="empty">No resolved trades yet -- check back once ideas start expiring.</p>'
    return f"""
    <table>
      <thead><tr><th>Strategy</th><th>Resolved</th><th>Win Rate</th><th>Total P&L</th><th>Avg Return</th><th>Premium/Credit</th><th>Capital</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """


def generate_performance():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    rows = _load_resolved()

    total_resolved = len(rows)
    wins = [r for r in rows if (r["realized_pnl"] or 0) > 0]
    overall_win_rate = round(len(wins) / total_resolved * 100, 1) if total_resolved else None
    total_pnl = round(sum(r["realized_pnl"] or 0 for r in rows), 2)
    returns = [r["pct_return_on_capital"] for r in rows if r["pct_return_on_capital"] is not None]
    avg_return = round(sum(returns) / len(returns), 2) if returns else None

    buckets = _csp_bucket_breakdown(rows)
    strategy_perf = _strategy_performance(rows)
    validation = _score_validation(rows)

    stats_html = ""
    if total_resolved:
        stats_html = f"""
        <div class="stats">
          <div class="stat"><div class="stat-num">{total_resolved}</div><div class="stat-label">Resolved</div></div>
          <div class="stat"><div class="stat-num">{overall_win_rate}%</div><div class="stat-label">Win Rate</div></div>
          <div class="stat"><div class="stat-num" style="color:{'#15803d' if total_pnl >= 0 else '#b91c1c'}">${total_pnl:,.2f}</div><div class="stat-label">Total P&L</div></div>
          <div class="stat"><div class="stat-num">{f"{avg_return:+.1f}%" if avg_return is not None else '—'}</div><div class="stat-label">Avg Return</div></div>
        </div>
        """

    validation_html = ""
    if validation["n_winners"] or validation["n_losers"]:
        w = validation["avg_score_winners"]
        l = validation["avg_score_losers"]
        validation_html = f"""
        <section>
          <h2>Does the Score Predict the Outcome?</h2>
          <p class="section-note">Average composite score of winning trades vs. losing trades. If scoring is doing its job, winners should average meaningfully higher.</p>
          <div class="validation-cards">
            <div class="validation-card">
              <div class="validation-label">Winners ({validation['n_winners']})</div>
              <div class="validation-num" style="color:#15803d">{w if w is not None else '—'}</div>
            </div>
            <div class="validation-card">
              <div class="validation-label">Losers ({validation['n_losers']})</div>
              <div class="validation-num" style="color:#b91c1c">{l if l is not None else '—'}</div>
            </div>
          </div>
        </section>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wheelhouse — Performance</title>
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
  .stats {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .stat {{ text-align: center; }}
  .stat-num {{ font-size: 22px; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  main {{ max-width: 1100px; margin: 0 auto; }}
  section {{ margin-bottom: 36px; }}
  h2 {{ font-size: 16px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 2px; }}
  .section-note {{ color: var(--muted); font-size: 12.5px; margin: 4px 0 14px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  th {{ text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 10px 14px; border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--border); }}
  tr:hover td {{ background: var(--row-hover); }}
  tr:last-child td {{ border-bottom: none; }}
  .bucket, .strat {{ font-weight: 700; }}
  .winrate {{ font-weight: 700; color: var(--accent); }}
  .empty {{ text-align: center; color: var(--muted); font-style: italic; padding: 30px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; }}
  .validation-cards {{ display: flex; gap: 16px; }}
  .validation-card {{ flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px; text-align: center; }}
  .validation-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }}
  .validation-num {{ font-size: 32px; font-weight: 700; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>🎡 Wheelhouse — Performance</h1>
    <div class="subtitle">Resolved trade outcomes, official scheduled record only ·
      <a class="nav-link" href="index.html">← Today's report</a> ·
      <a class="nav-link" href="history.html">View history →</a>
    </div>
  </div>
  {stats_html}
</header>
<main>
  {validation_html}
  <section>
    <h2>CSP / Leveraged CSP Outcomes by Score Bucket</h2>
    <p class="section-note">Worthless vs. assigned, grouped by the composite score the trade had when it was recommended.</p>
    {_bucket_table_html(buckets)}
  </section>
  <section>
    <h2>Performance by Strategy</h2>
    <p class="section-note">Premium/credit and capital figures use different bases per strategy (cash-secured collateral for CSPs, spread width for spreads, cost basis for LEAPs) since they aren't directly comparable.</p>
    {_strategy_table_html(strategy_perf)}
  </section>
</main>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"Performance page written to {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_performance()
