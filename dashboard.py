"""
Interactive dashboard for the options analyst tool.

Run with:  streamlit run dashboard.py

Lets you trigger a scan, filter/sort results per strategy, and drill into
the reasoning (sub-scores, technicals, IV context) behind each idea.
"""

import streamlit as st
import pandas as pd
from config import all_tickers, UNIVERSE, MAX_IDEAS_PER_STRATEGY
from pipeline import run_pipeline, analyze_ticker

st.set_page_config(page_title="Wheelhouse", layout="wide")

st.title("🎡 Wheelhouse")
st.caption(
    "Screens cash-secured puts, credit spreads, and LEAPs across your universe, "
    "then scores and ranks ideas by technicals, IV, premium, risk, and catalysts. "
    "Informational only — not investment advice."
)

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Scan Controls")
    bucket_choices = st.multiselect(
        "Universe buckets", options=list(UNIVERSE.keys()), default=list(UNIVERSE.keys())
    )
    selected_tickers = [t for b in bucket_choices for t in UNIVERSE[b]]
    st.write(f"{len(selected_tickers)} tickers selected")

    run_button = st.button("🔍 Run Scan", type="primary", use_container_width=True)

    st.divider()
    st.caption(
        "Edit `config.py` to change screening thresholds and scoring weights — "
        "this dashboard reflects whatever's in that file."
    )

if "results" not in st.session_state:
    st.session_state.results = None

if run_button:
    progress = st.progress(0, text="Starting scan...")
    all_ideas = []
    for i, ticker in enumerate(selected_tickers, 1):
        progress.progress(i / len(selected_tickers), text=f"Analyzing {ticker}...")
        all_ideas += analyze_ticker(ticker, verbose=False)
    progress.empty()

    df = pd.DataFrame(all_ideas)
    if not df.empty:
        df["composite_score"] = df["scores"].apply(lambda s: s["composite"])
    st.session_state.results = df
    st.session_state.scanned_at = pd.Timestamp.now()

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
df = st.session_state.results

if df is None:
    st.info("Set your universe in the sidebar and click **Run Scan** to generate ideas.")
elif df.empty:
    st.warning("No candidates passed the screening rules. Try loosening thresholds in config.py.")
else:
    st.caption(f"Last scanned: {st.session_state.scanned_at.strftime('%Y-%m-%d %H:%M')}")
    tabs = st.tabs(["Cash-Secured Puts", "Leveraged ETF CSPs", "Spreads", "LEAPs", "All Ideas (raw)"])

    from config import MIN_SCORE_TO_REPORT

    def render_strategy_tab(strategy_key, display_cols, sort_col="composite_score"):
        sub = df[df["strategy"] == strategy_key].copy()
        sub = sub[sub["composite_score"] >= MIN_SCORE_TO_REPORT[strategy_key]]
        sub = sub.sort_values(sort_col, ascending=False).head(MAX_IDEAS_PER_STRATEGY)
        if sub.empty:
            st.write("No ideas cleared the score threshold for this strategy.")
            return
        for _, row in sub.iterrows():
            with st.expander(
                f"**{row['ticker']}** — {row.get('sub_type', strategy_key.upper())} "
                f"— exp {row['expiry']} ({row['dte']}d) — score **{row['composite_score']}**"
            ):
                col1, col2 = st.columns([2, 1])
                with col1:
                    detail = {k: v for k, v in row.items()
                              if k not in ("scores", "trend_diagnostics", "iv_diagnostics")}
                    st.table(pd.DataFrame(detail.items(), columns=["field", "value"]))
                with col2:
                    st.write("**Sub-scores**")
                    st.bar_chart(pd.Series(row["scores"]).drop("composite"))
                    st.metric("Composite Score", row["scores"]["composite"])
                    st.write("**Trend**")
                    st.json(row["trend_diagnostics"], expanded=False)
                    st.write("**IV context**")
                    st.json(row["iv_diagnostics"], expanded=False)

    with tabs[0]:
        render_strategy_tab("csp", [])
    with tabs[1]:
        render_strategy_tab("leveraged_csp", [])
    with tabs[2]:
        render_strategy_tab("spread", [])
    with tabs[3]:
        render_strategy_tab("leaps", [])
    with tabs[4]:
        st.dataframe(df.drop(columns=["scores", "trend_diagnostics", "iv_diagnostics"],
                              errors="ignore"))
