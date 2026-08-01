# Wheelhouse

An autonomous screener that scans a configurable universe of tickers,
identifies cash-secured put, credit spread, and LEAPs setups, scores them
against technicals/IV/premium/risk/catalysts, and surfaces the best ideas
as a daily HTML dashboard.

**Daily report format:** always shows your best 5 cash-secured puts (your
core strategy), plus any spread or LEAPs ideas that score exceptionally well
(85+) that day as bonus opportunities. Every idea includes an AI-written
thesis explaining why it screened well, the key risk, and what would
invalidate it — generated from the actual screened numbers, not news or
speculation. Tune the count/threshold in `config.py`
(`REPORT_CSP_COUNT`, `REPORT_EXCEPTIONAL_THRESHOLD`, `REPORT_MAX_BONUS_IDEAS`).

**This tool produces informational output for your own research. It is not
a licensed financial advisor and doesn't place trades.**

## Option A: No-code setup (recommended if you don't code)

This runs the scan automatically every weekday morning and publishes a
webpage you check like any other website. Total cost: $0. You'll create one
free account and click through some settings — no terminal, no editing code.

### Step 1 — Create a free GitHub account
Go to [github.com](https://github.com) → Sign up. Just an email/password like
any other account.

### Step 2 — Create a new repository
Click the **+** icon (top right) → **New repository**. Name it `wheelhouse`
(or anything you like — just remember whatever you pick, since it's part of
your dashboard's URL later). Leave it **Public** (required for the free
dashboard hosting). Click **Create repository**.

### Step 3 — Upload the project files
On your new repo's page, click **uploading an existing file** (or drag-and-drop).
Unzip the file I gave you on your computer first, then drag the *entire
contents* of the `wheelhouse` folder into the browser upload area — all
the `.py` files, `requirements.txt`, `README.md`, the `strategies` folder,
`.github` folder, and `docs` folder together. Scroll down, click
**Commit changes**.

> Note: folders starting with a dot (like `.github`) can be tricky to
> drag-and-drop in some browsers. If it doesn't appear after upload, click
> **Add file → Create new file**, type `.github/workflows/daily_scan.yml` as
> the filename (GitHub auto-creates the folders), and paste in the contents
> of that file from your unzipped folder. Same trick works for any file that
> doesn't upload cleanly.

### Step 4 — Turn on GitHub Pages (this makes your dashboard a real webpage)
In your repo, go to **Settings → Pages** (left sidebar). Under "Build and
deployment," set **Source** to "Deploy from a branch," **Branch** to `main`,
folder to `/docs`. Click **Save**. GitHub will give you a URL like
`https://yourusername.github.io/wheelhouse/` — that's your dashboard's
permanent address. Bookmark it now.

### Step 5 — Add your Anthropic API key (powers the AI-written thesis for each idea)
1. Go to [console.anthropic.com](https://console.anthropic.com) → sign up (free) →
   **Get API Keys** → **Create Key**. Copy the key it gives you (starts with `sk-ant-`).
   You'll need to add a small amount of credit ($5 minimum covers months of this).
2. Back in your GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret**. Name it exactly `ANTHROPIC_API_KEY`, paste your key, save.

> If you skip this step, the report still works — it just falls back to a
> plainer, template-written thesis instead of the AI-written one.

### Step 6 — Run your first scan
Go to the **Actions** tab in your repo. You should see "Daily Options Scan."
Click it, then click **Run workflow** (dropdown) → **Run workflow** (green
button). It takes a few minutes. When the checkmark turns green, visit your
bookmarked URL — your real dashboard is live.

After this, it re-runs automatically every weekday morning on its own —
nothing to click. Each morning it overwrites the page with fresh ideas.

### Step 7 (optional) — Get pinged on Slack when it's done
1. In Slack, create an **Incoming Webhook** for a channel (ask your Slack
   admin, or search "Slack incoming webhooks" — it's a URL Slack gives you).
2. In your GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret**. Name it `SLACK_WEBHOOK_URL`, paste the URL, save.
3. Edit `.github/workflows/daily_scan.yml` in GitHub's web editor (click the
   file, click the pencil icon) and replace `YOUR_GITHUB_USERNAME` and
   `YOUR_REPO_NAME` in the Slack message line with your actual GitHub
   username and repo name. Commit.

### Adjusting your "style" without coding
Click `config.py` in your GitHub repo → pencil icon (Edit) → change any
number (e.g. `min_iv_rank`, delta ranges, scoring weights) → **Commit
changes**. That's it — the next scheduled run uses your new settings. You're
editing numbers in a text box, not writing code.

---

## Option B: Run it yourself locally (if you become comfortable with code later)

## Setup

```bash
cd wheelhouse
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run it

**Dashboard (recommended):**
```bash
streamlit run dashboard.py
```
Opens in your browser. Pick your universe buckets in the sidebar, click
"Run Scan," and drill into results by strategy tab.

**Command line (for quick checks or cron jobs):**
```bash
python pipeline.py
```
Prints a ranked summary per strategy to the console.

## Project structure

```
config.py           <- YOUR STYLE LIVES HERE: universe, screening thresholds, scoring weights
data_fetch.py        <- price history + options chain retrieval (yfinance backend)
greeks.py             <- Black-Scholes delta estimation (yfinance doesn't provide greeks)
technicals.py          <- trend/RSI/support scoring
iv_metrics.py            <- IV rank proxy vs historical realized vol
strategies/
  csp.py                    <- cash-secured put candidate generation
  spreads.py                 <- credit spread candidate generation
  leaps.py                    <- LEAPs candidate generation
scoring.py             <- composite scoring engine, weighted per config.py
pipeline.py           <- orchestrates the full scan, callable standalone or from dashboard
dashboard.py         <- Streamlit UI
```

## Tuning it to your style

Everything you'd want to adjust lives in `config.py`:
- **UNIVERSE**: add/remove tickers, organize into buckets (buckets can have
  different rules — e.g. leveraged ETFs are already handled more strictly)
- **SCREEN**: hard filters (delta ranges, DTE windows, min OI, min IV rank,
  min annualized return, etc.) — anything failing these never reaches scoring
- **SCORING_WEIGHTS**: how much each sub-factor (technicals/IV/premium/risk/
  catalyst) counts toward the composite score, per strategy
- **MIN_SCORE_TO_REPORT / MAX_IDEAS_PER_STRATEGY**: how selective the final
  report is

Change a number, rerun the scan — no code changes needed for day-to-day tuning.

## Roadmap / next steps

1. **Validate against a broker's real numbers.** yfinance's IV/greeks are
   approximations. Before trusting this for sizing, sanity-check a handful
   of ideas against your broker's live chain.
2. **Upgrade the data backend.** Swap `data_fetch.py` for Tradier or
   Polygon.io once you want more reliable/real-time chains — nothing else
   in the codebase needs to change if you keep the same function signatures.
3. **True IV rank.** Replace the realized-vol proxy in `iv_metrics.py` with
   real historical IV series (Tradier/ORATS provide this) for a materially
   better IV rank read.
4. **Automate the daily run.** Options:
   - Cron job running `python pipeline.py` and emailing/Slacking the output
   - Deploy the Streamlit app to Streamlit Community Cloud or a small VPS
     so it's always accessible, with a scheduled scan populating results
5. **Persistence.** Right now each scan is stateless. Consider logging
   daily results to a SQLite/Postgres table so you can track how scored
   ideas actually performed over time — this is how you validate (and
   improve) the scoring weights.
6. **Position tracking.** Once you're acting on ideas, a simple table of
   open positions (entry, strikes, current P/L) turns this from an idea
   generator into a lightweight portfolio dashboard too.

## Known limitations (read before trusting scores)

- Greeks are Black-Scholes estimates, not live broker greeks
- IV rank is a realized-vol proxy until you wire in real historical IV
- Earnings dates come from yfinance and can be approximate/unconfirmed
- No slippage/commission modeling in return calculations
- Liquidity filters (OI, spread %) are a floor, not a guarantee of fills
