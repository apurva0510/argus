# Argus: AI Infrastructure & Data-Center Stock Monitor

Argus is a lightweight, local-first Streamlit research application designed to monitor stocks in sectors linked to AI infrastructure and data centers (power/grid, cooling, optical networking, semiconductor equipment, data center REITs). It helps identify high-quality stock pullbacks, tracks recent SEC filings and news catalysts, constructs a custom AI Infra Core index, and sends email alerts.

Argus is designed for a simple, two-user family workflow (research and decision support). It is not a trading execution platform.

---

## 🚀 Quick Start & Installation

Follow these steps to set up Argus on your local machine.

### 1. Environment Setup
Argus requires **Python 3.12** or higher. Create a virtual environment and activate it:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate
```

### 2. Install Dependencies
Install dependencies from `requirements.txt` and install the package in **editable mode**. 

> [!TIP]
> Installing in editable mode (`-e .`) registers the `argus` package with your virtual environment, ensuring all import paths resolve correctly and preventing common path errors.

```bash
# Install core requirements
pip install -r requirements.txt

# Install package in editable mode
pip install -e .
```

### 3. Environment Configuration
Copy the template configuration file to create your local `.env` file:

```bash
cp .env.example .env
```

Open `.env` in a text editor to configure settings. Key configurations include:
- `APP_PASSWORD`: Set a shared password to protect the dashboard (leave blank to disable login).
- `SEC_USER_AGENT`: Required format for SEC filings (e.g., `Argus/1.0 (contact@example.com)`).
- `MARKET_DATA_PROVIDER`: Set to `yfinance` (default, free, no key required) or configure optional API keys for `finnhub`, `twelvedata`, or `alphavantage`.
- SMTP details (`EMAIL_HOST`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_TO`) for email alerts.

---

## 💾 Database and Data Ingestion Pipeline

Argus uses a local SQLite database at `data/app.db`. Run these commands sequentially to prepare the database and backfill market data:

### 1. Initialize Schema & Seed Universe
Initialize the database file and seed it with the default universe of companies and themes:

```bash
# Create tables
python scripts/init_db.py

# Seed initial stock list and watchlists
python scripts/seed_companies.py
```

### 2. Backfill Prices & Compute Metrics
Ingest historical pricing data, compute relative metrics (vs. QQQ and NVDA), and generate Pullback Finder scores:

```bash
# Ingest 2 years of daily price history
python scripts/backfill_prices.py --period 2y

# Compute technical/moving average indicators
python scripts/compute_metrics.py

# Calculate opportunity and pullback scores
python scripts/compute_scores.py
```

### 3. (Optional) Ingest News & SEC Filings
Fetch news headlines and company filings from RSS/GDELT and SEC EDGAR:

```bash
# Refresh news articles (uses rate limit protection)
python scripts/refresh_news.py

# Refresh SEC filings (requires valid SEC_USER_AGENT in .env)
python scripts/refresh_filings.py
```

### 4. Evaluate Alert Rules
Evaluate watchlist metrics against your enabled alert parameters (sends emails for triggers):

```bash
python scripts/run_alerts.py
```

### 5. Orchestrated Daily Refresh
Instead of running individual scripts, use the daily orchestrator to sync prices, compute metrics/scores, retrieve news, filings, and evaluate alerts in one command:

```bash
# Run the complete refresh workflow
python scripts/run_daily_refresh.py --period 2y
```

Useful daily workflow flags:
- `--skip-news`: Skip fetching news headlines.
- `--skip-filings`: Skip checking SEC filings.
- `--skip-alerts`: Skip checking alert triggers.
- `--force`: Force news refresh bypassing the 3-hour cache check.

---

## 🖥️ Running the Application

Start the Streamlit dashboard on your local machine:

```bash
streamlit run app/main.py
```
The application will be accessible at [http://localhost:8501](http://localhost:8501). If `APP_PASSWORD` is defined in your `.env`, you will be greeted by a secure login page.

---

## 🧪 Testing and Quality Control

### Run Tests
To execute the unit and integration test suite, run:

```bash
pytest
```
*Note: The test suite runs in ~30 seconds, uses SQLite in-memory fixtures, and mocks all external API/network requests.*

### Run Linter
To check for syntax, format, or type issues, run:

```bash
ruff check .
```

---

## 🛠️ Troubleshooting

### 1. `ModuleNotFoundError: No module named 'app'` or `'argus'`
This occurs if python cannot find the internal packages when executing scripts or running tests.
* **Fix**: Ensure you have installed the package in editable mode (`pip install -e .`) inside your active virtual environment. Alternatively, manually prefix commands with `PYTHONPATH=.` (e.g. `PYTHONPATH=. python scripts/init_db.py`).

### 2. `sqlite3.OperationalError: database is locked`
SQLite supports multiple concurrent readers but only one concurrent writer. If a script freezes or throws this error, another ingestion script or the Streamlit app might be in the middle of a write transaction.
* **Fix**: Check for and terminate dangling python ingestion processes. If the database remains locked, delete `data/app.db-journal` if it exists, or restart the Streamlit server.

### 3. `SEC submissions API failed` or `403 Forbidden` for SEC EDGAR
The SEC strictly requires a descriptive `User-Agent` header containing contact details. Without it, requests are rejected with a 403 error.
* **Fix**: Open `.env` and ensure `SEC_USER_AGENT` is configured with a format like `Company/Version (contact@email.com)`. Do not use generic user agents.

### 4. Twelve Data or Alpha Vantage Rate Limits
Alternative API providers on free tiers have strict limits (e.g., 5 calls per minute or 500 calls per day). Ingesting historical prices for 30+ tickers will exhaust these immediately.
* **Fix**: Use the default `yfinance` provider (`MARKET_DATA_PROVIDER=yfinance`), which has no API key requirement and high rate limits. Use alternative providers only for testing.

---

## ☁️ Deployment Notes (VPS or PaaS)

Since Argus is a local-first application built around a local SQLite database, deploying to ephemeral host providers (like Streamlit Community Cloud) will cause your database to reset every time the server spins down. 

For a persistent, cloud-based setup:

1. **Deploy to a VPS or PaaS with Volume Support**:
   Use host providers like **Render**, **Railway**, **Fly.io**, or **DigitalOcean** that support attaching a small persistent volume.
2. **Mount the SQLite Database**:
   Mount a persistent disk directory to the `data/` folder inside the workspace. Update your `DATABASE_URL` in env variables to point to the mounted path (e.g. `sqlite:////mnt/persistent/app.db`).
3. **Daily Ingestion Cron**:
   Configure a simple server-side cron job or task scheduler on the VPS to trigger the orchestrator daily:
   ```cron
   0 18 * * 1-5 /path/to/project/.venv/bin/python /path/to/project/scripts/run_daily_refresh.py --skip-news
   ```
4. **No Docker Required**:
   Install Python 3.12 directly, clone the repository, install standard requirements, and run the Streamlit daemon using systemd, PM2, or background execution.

---

## 📈 AI Infra Core Index Methodology

The custom **AI Infra Core Index** is built to monitor the collective performance of AI infrastructure and data-center supplier stocks.

* **Equal Weighted**: The index is an equal-weighted average of all active constituent stocks.
* **Base Level**: Set to a base of 100.0. The chart on the Dashboard dynamically rebases the index level to 100 on the starting date of the selected timeframe for easy comparison.
* **Dynamic Rebalancing / Missing History**: IPOs (e.g., `GEV` or `ALAB`) and companies with missing historical price bars are handled gracefully. The daily index return is the average of daily returns of only those constituents that have valid price data on both the current and the previous trading day. This average return is compounded daily.
* **Exclusions**: Benchmark-only and large hyperscaler names (`QQQ`, `NVDA`, `MSFT`, `AMZN`, `GOOGL`, `META`) and optional highly aggressive stocks (`ALAB`, `CRDO`) are excluded from the index calculation by default.

---

## ✅ MVP Delivery Checklist

- [x] **Visual Dashboard**: KPI cards, index trend comparisons, top movers, stale-data warnings, and upcoming catalyst lists.
- [x] **Interactive Watchlists**: Sector-grouped tables allowing in-line status updates and persistent custom notes.
- [x] **Detail Ticker Analytics**: Interactive Plotly pricing charts, moving averages, relative strength calculations, and local notes editor.
- [x] **Explainable Pullback Finder**: Quantitative Opportunity Score incorporating pullback, technical setup, and relative strength metrics.
- [x] **Catalyst Feeds Ingestion**: SEC EDGAR filings and RSS/GDELT news feed ingestion with keyword highlight tagging.
- [x] **Idempotent Ingestion Auditing**: Fully automated job logger logging runs to `job_runs`.
- [x] **Watchlist-linked Email Alerts**: Triggerable rules evaluating indicators with a 24h duplicate notification filter.
- [x] **AI Infra Core Index**: Custom equal-weight benchmark construction, index contribution attribution, and visual metrics.
- [x] **Multi-Provider Abstraction**: Plug-and-play architecture supporting yfinance, Finnhub, Twelve Data, and Alpha Vantage.
- [x] **Password Protection**: Simple shared credentials lockout system using `APP_PASSWORD`.
- [x] **Data Health & API Inspection**: Self-healing check panel monitoring ingestion delays, active keys, and logs.
