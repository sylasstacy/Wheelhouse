"""
SQLite-backed history: logs every idea actually shown in the daily report,
and later resolves what would have happened had you traded it.

The database file (wheelhouse.db) lives at the repo root and is committed
alongside docs/index.html by the same GitHub Actions step -- no new service,
no new account, no new API key.

Schema:
  daily_ideas -- one row per idea shown in a given day's report
  outcomes    -- one row per resolved idea, populated by resolve_outcomes.py
                 once that idea's expiry date has passed
"""

from __future__ import annotations
import datetime as dt
import json
import sqlite3

DB_PATH = "wheelhouse.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    ticker TEXT NOT NULL,
    bucket TEXT,
    expiry TEXT,
    dte INTEGER,
    rank_in_section INTEGER,
    composite_score REAL,
    technicals_score REAL,
    iv_score REAL,
    premium_score REAL,
    risk_score REAL,
    catalyst_score REAL,
    underlying_price REAL,
    idea_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_ideas_scan_date ON daily_ideas(scan_date);
CREATE INDEX IF NOT EXISTS idx_daily_ideas_ticker ON daily_ideas(ticker);
CREATE INDEX IF NOT EXISTS idx_daily_ideas_strategy ON daily_ideas(strategy);
CREATE INDEX IF NOT EXISTS idx_daily_ideas_expiry ON daily_ideas(expiry);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL UNIQUE REFERENCES daily_ideas(id),
    resolved_date TEXT NOT NULL,
    underlying_price_at_expiry REAL,
    outcome TEXT NOT NULL,
    realized_pnl REAL,
    pct_return_on_capital REAL,
    notes TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def log_daily_ideas(sections: dict, scan_date: str = None) -> int:
    """
    Logs every idea actually shown in today's report.

    sections: dict of {strategy_label: dataframe}, e.g.
        {"csp": core_df, "leveraged_csp": leveraged_df,
         "spread": spread_df, "leaps": leaps_df}
    Each dataframe's rows must be idea dicts as produced by scoring.py
    (i.e. must include a "scores" dict with the five sub-scores + composite).

    Returns the number of rows inserted.
    """
    scan_date = scan_date or dt.date.today().isoformat()
    init_db()
    conn = get_connection()
    inserted = 0
    try:
        for strategy, df in sections.items():
            if df is None or df.empty:
                continue
            ranked = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
            for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
                idea = row.to_dict()
                scores = idea.get("scores", {})
                conn.execute(
                    """
                    INSERT INTO daily_ideas (
                        scan_date, strategy, ticker, bucket, expiry, dte,
                        rank_in_section, composite_score, technicals_score,
                        iv_score, premium_score, risk_score, catalyst_score,
                        underlying_price, idea_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_date, strategy, idea.get("ticker"), idea.get("bucket"),
                        idea.get("expiry"), idea.get("dte"), rank,
                        scores.get("composite"), scores.get("technicals"),
                        scores.get("iv"), scores.get("premium"), scores.get("risk"),
                        scores.get("catalyst"), idea.get("underlying_price"),
                        json.dumps(idea, default=str),
                    ),
                )
                inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def get_unresolved_expired_ideas(as_of: str = None) -> list:
    """Returns daily_ideas rows whose expiry has passed and have no outcome yet."""
    as_of = as_of or dt.date.today().isoformat()
    init_db()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT d.* FROM daily_ideas d
            LEFT JOIN outcomes o ON o.idea_id = d.id
            WHERE o.id IS NULL AND d.expiry IS NOT NULL AND d.expiry <= ?
            """,
            (as_of,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_outcome(idea_id: int, underlying_price_at_expiry, outcome: str,
                    realized_pnl, pct_return_on_capital, notes: str = "") -> None:
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO outcomes (
                idea_id, resolved_date, underlying_price_at_expiry,
                outcome, realized_pnl, pct_return_on_capital, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (idea_id, dt.date.today().isoformat(), underlying_price_at_expiry,
             outcome, realized_pnl, pct_return_on_capital, notes),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_history(limit_days: int = 60) -> list:
    """Returns recent daily_ideas joined with their outcome (if resolved yet),
    most recent scan_date first -- used to render docs/history.html."""
    init_db()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT d.*, o.outcome, o.realized_pnl, o.pct_return_on_capital,
                   o.underlying_price_at_expiry
            FROM daily_ideas d
            LEFT JOIN outcomes o ON o.idea_id = d.id
            WHERE d.scan_date >= date('now', ?)
            ORDER BY d.scan_date DESC, d.strategy, d.rank_in_section
            """,
            (f"-{limit_days} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
