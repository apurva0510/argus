# Argus: AI Infrastructure & Emerging Compute Stock Monitor

Argus is a lightweight Streamlit research application designed to monitor stocks in sectors linked to AI infrastructure and data centers (AI semiconductors and memory, power/grid, cooling, optical networking, and semiconductor equipment) plus separate Emerging Compute themes such as quantum computing. It supports a local SQLite database for development and a hosted PostgreSQL database (such as Supabase) for production deployment. It helps identify high-quality stock pullbacks, tracks recent SEC filings and news catalysts, constructs a custom AI Infra Core index, and sends email alerts.

Argus is designed for a simple, two-user family workflow (research and decision support). It is not a trading execution platform.

---

## Quick Start & Installation

Follow these steps to set up Argus on your local machine.

### 1. Environment Setup

Argus requires **Python 3.12** or higher. Create the uv-managed environment and install dependencies:

```bash
uv sync
```

### 2. Install Dependencies

`uv sync` installs dependencies from `requirements.txt` and installs the package in **editable mode**.

> [!TIP]
> Installing in editable mode (`-e .`) registers the `argus` package with your virtual environment, ensuring all import paths resolve correctly and preventing common path errors.

### 3. Environment Configuration

Copy the template configuration file to create your local `.env` file:

```bash
cp .env.example .env
```

Open `.env` in a text editor to configure settings. Key configurations include:

- `APP_PASSWORD`: Set a shared password to protect the dashboard (leave blank to disable login).
- `APP_AUTH_SECRET`: Optional signing secret for auth tokens and legacy auth cookies. If blank, Argus uses `APP_PASSWORD`.
- `SEC_USER_AGENT`: Required format for SEC filings (e.g., `Argus/1.0 (contact@example.com)`).
- `MARKET_DATA_PROVIDER`: Set to `yfinance` (default, free, no key required) or configure optional API keys for `finnhub`, `twelvedata`, or `alphavantage`.
- SMTP details (`EMAIL_HOST`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_TO`) for email alerts. `EMAIL_TO` supports comma-separated recipients.
- For Supabase/Postgres, either:
  - put full credentials in `DATABASE_URL`, or
  - keep a placeholder in `DATABASE_URL` (`[YOUR-PASSWORD]`, `<PASSWORD>`, or `__DB_PASSWORD__`) and set `DATABASE_PASSWORD`.

---

## Database and Data Ingestion Pipeline

Argus uses a local SQLite database at `data/app.db` by default, or PostgreSQL if `DATABASE_URL` is configured. Run these commands sequentially to prepare the database and backfill market data:

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

# Refresh recent 15-minute bars during market hours
python scripts/backfill_prices.py --period 5d --interval 15m

# Compute technical/moving average indicators
python scripts/compute_metrics.py

# Refresh fundamentals used by peer-relative valuation
python scripts/refresh_fundamentals.py

# Compute peer-relative valuation snapshots from refreshed fundamentals
python scripts/compute_valuation_peers.py

# Calculate opportunity and pullback scores
python scripts/compute_scores.py

# Pre-calculate AI Infra Core Index values
python scripts/refresh_index.py

# Compute rich signals (NVDA/hyperscaler correlation, capex growth, power demand, etc.)
python scripts/compute_signals.py

# Generate read-only company theses from current Argus data
python scripts/generate_theses.py
```

### 3. (Optional) Ingest News, IR Feeds & SEC Filings

Fetch news headlines and company filings from RSS and SEC EDGAR:

```bash
# Refresh broad market news articles (uses provider cooldown protection)
python scripts/refresh_news.py

# Refresh selected company investor-relations feeds
python scripts/refresh_ir_feeds.py

# Refresh SEC filings (requires valid SEC_USER_AGENT in .env)
python scripts/refresh_ciks.py
python scripts/refresh_filings.py
```

### 4. (Optional) Refresh Macro & Capex Context

Refresh FRED macro indicators, automated or manual hyperscaler capex data, and macro release schedules:

```bash
# Refresh Treasury yields and inflation indicators from FRED
python scripts/refresh_macro.py

# Ingest upcoming FRED release schedules (requires FRED_API_KEY)
python scripts/refresh_release_calendar.py

# Ingest automated capex from SEC CompanyFacts (MSFT, AMZN, GOOGL, META)
python scripts/refresh_capex.py

# Add a manual quarterly capex observation (fallback / overrides)
python scripts/add_capex_observation.py --ticker MSFT --period-end 2026-03-31 --capex 10000000000 --source-label "Q1 earnings"
```

### 5. Pullback Backtesting & Catalyst Impact (Release B)

Run historical backtests for opportunity scores and analyze price reactions to catalyst events (earnings releases and SEC filings):

```bash
# Run daily historical backtest (default start is 180 days ago)
python scripts/backtest_scores.py --start-date 2026-01-01

# Refresh catalyst impact snapshots and calculate price reactions/drifts
python scripts/refresh_catalysts.py
```

### 6. Evaluate Alert Rules

Evaluate watchlist metrics against your enabled alert parameters (sends emails for triggers):

```bash
python scripts/run_alerts.py
```

### 7. Orchestrated Daily Refresh

Instead of running individual scripts, use the daily orchestrator to sync daily prices, macro data, metrics/scores, index values, generated theses, and alerts in one command. Scheduled production jobs handle news, IR feeds, intraday prices, and SEC filings separately through GitHub Actions:

```bash
# Run the complete refresh workflow
python scripts/run_daily_refresh.py --period 2y
```

Useful daily workflow flags:

- `--skip-news`: Skip fetching news headlines.
- `--skip-filings`: Skip checking SEC filings.
- `--skip-alerts`: Skip checking alert triggers.
- `--skip-macro`: Skip FRED macro refresh.

---

## 🖥️ Running the Application

Start the Streamlit dashboard on your local machine:

```bash
streamlit run app/main.py
```

The application will be accessible at [http://localhost:8501](http://localhost:8501). If `APP_PASSWORD` is defined in your `.env`, you will be greeted by a secure login page.

---

## Testing and Quality Control

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

## Troubleshooting

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

## Deployment with Supabase Postgres

Argus supports both **local SQLite** (default) and **Supabase Postgres** for production deployment. When `DATABASE_URL` is set, all pipelines and the Streamlit app will use that connection instead of the local SQLite file.

### 1. Supabase Project Setup

1. Create a free project at [supabase.com](https://supabase.com).
2. In **Settings → Database**, copy the **Connection string (URI)** — it looks like:

   ```
   postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```

   You can also store this as:

   - `DATABASE_URL=postgresql://postgres.[project-ref]:[YOUR-PASSWORD]@...`
   - `DATABASE_PASSWORD=your-actual-password`
3. Initialize the schema and seed data by running the standard scripts with `DATABASE_URL` set. `init_db.py` creates the current schema and records the schema version used for future hosted upgrades:

   ```bash
   DATABASE_URL="postgresql://..." python scripts/init_db.py
   DATABASE_URL="postgresql://..." python scripts/seed_companies.py
   ```
4. Backfill prices and compute metrics:

   ```bash
   DATABASE_URL="postgresql://..." python scripts/backfill_prices.py --period 2y
   DATABASE_URL="postgresql://..." python scripts/backfill_prices.py --period 5d --interval 15m
   DATABASE_URL="postgresql://..." python scripts/compute_metrics.py
   DATABASE_URL="postgresql://..." python scripts/compute_scores.py
   DATABASE_URL="postgresql://..." python scripts/refresh_index.py
   ```

> [!NOTE]
> Argus automatically normalizes `postgresql://` prefixes to `postgresql+psycopg://` for SQLAlchemy 2.0 compatibility. You do not need to modify the Supabase URI.

### 2. Streamlit Community Cloud Secrets

To deploy the Streamlit app on [Streamlit Community Cloud](https://streamlit.io/cloud):

1. Push your repo to GitHub.
2. Create a new app on Streamlit Cloud pointing to `app/main.py`.
3. In the app's **Settings → Secrets**, add a TOML block:
   ```toml
   DATABASE_URL = "postgresql://postgres.[ref]:[YOUR-PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres"
   DATABASE_PASSWORD = "your-actual-password"
   APP_PASSWORD = "your-shared-password"
   APP_AUTH_SECRET = "a-long-random-cookie-signing-secret"
   SEC_USER_AGENT = "Argus/1.0 (your-email@example.com)"
   ```

> [!IMPORTANT]
> Never commit secrets to your repository. The Streamlit secrets panel and GitHub Actions secrets are the only places credentials should live.

> [!NOTE]
> Supabase Row Level Security is managed in the Supabase project configuration. Argus does not require a repo-managed RLS script.

### 3. GitHub Actions — Automated Refresh Schedules

Argus includes five workflow files for production scheduling:

- `.github/workflows/intraday-prices.yml`
  - Every 30 minutes on weekdays
  - Executes only during the ET market window (9:30 AM–4:00 PM)
  - Runs: yfinance 15-minute prices (`--period 5d --interval 15m`) → metrics → daily index refresh → alerts
- `.github/workflows/news-refresh.yml`
  - Every 2 hours, every day
  - Runs: RSS news refresh with 24-hour provider cooldown after HTTP 429 → signals → alerts
- `.github/workflows/filings-refresh.yml`
  - Every 3 hours, every day
  - Runs: official SEC ticker-to-CIK synchronization → SEC filings refresh → alerts
- `.github/workflows/ir-feeds-refresh.yml`
  - Every 6 hours, every day, at minute 22 UTC (`22 */6 * * *`)
  - Runs: selected investor-relations feed refresh → signals → alerts
- `.github/workflows/daily-refresh.yml`
  - Once after US market close on weekdays during the 4:00–7:00 PM ET gated window
  - Runs: daily bars, 1-day 15-minute close-marker bars, macro indicators, metrics, scores, index, and alerts (`run_daily_refresh.py --period 2y --skip-news --skip-filings`)

**Required GitHub repository secrets** (Settings → Secrets and variables → Actions):

| Secret                | Description                                                    | Required |
| --------------------- | -------------------------------------------------------------- | -------- |
| `DATABASE_URL`      | Supabase Postgres connection string                            | ✅       |
| `DATABASE_PASSWORD` | Optional password if URL has placeholder                       | Optional |
| `SEC_USER_AGENT`    | SEC EDGAR user-agent header                                    | ✅       |
| `FRED_API_KEY`      | St. Louis Fed API key for macro calendars                      | Optional |
| `EIA_API_KEY`       | U.S. EIA API key for power signal metrics                      | Optional |
| `EMAIL_HOST`        | SMTP host for alert emails                                     | Optional |
| `EMAIL_USERNAME`    | SMTP username                                                  | Optional |
| `EMAIL_PASSWORD`    | SMTP password                                                  | Optional |
| `EMAIL_TO`          | Alert recipient email address(es), comma-separated if multiple | Optional |

### 4. Alternative: VPS or PaaS with SQLite

For a persistent SQLite deployment (no Postgres), deploy to a VPS or PaaS with volume support:

1. Use **Render**, **Railway**, **Fly.io**, or **DigitalOcean** with a persistent volume.
2. Mount a persistent disk to the `data/` folder. Set `DATABASE_URL=sqlite:////mnt/persistent/app.db`.
3. Configure a cron job for daily ingestion:
   ```cron
   0 18 * * 1-5 /path/to/project/.venv/bin/python /path/to/project/scripts/run_daily_refresh.py --skip-news
   ```
4. No Docker required — install Python 3.12, clone, install requirements, and run with systemd or PM2.

---

## AI Infra Core Index Methodology

The custom **AI Infra Core Index** is built to monitor the collective performance of AI infrastructure and data-center supplier stocks.

* **Equal Weighted**: The index is an equal-weighted average of all active constituent stocks.
* **Base Level**: Set to a base of 100.0. The chart on the Dashboard dynamically rebases the index level to 100 on the starting date of the selected timeframe for easy comparison.
* **Dynamic Rebalancing / Missing History**: IPOs (e.g., `GEV` or `ALAB`) and companies with missing historical price bars are handled gracefully. The daily index return is the average of daily returns of only those constituents that have valid price data on both the current and the previous trading day. This average return is compounded daily.
* **Exclusions**: Benchmark-only and large hyperscaler names (`QQQ`, `NVDA`, `MSFT`, `AMZN`, `GOOGL`, `META`), optional highly aggressive stocks (`ALAB`, `CRDO`), and Emerging Compute names such as Quantum Computing stocks are excluded from the AI Infra Core index calculation by default.

---

## Custom Index Lab

Argus includes an interactive **Index Lab** page (`app/pages/8_Index_Lab.py`) that allows users to define, backtest, and analyze custom index definitions:

* **Weighting Modes**:
  1. **Equal weight**: Distributes weights equally across all selected constituent tickers.
  2. **Theme exposure weight**: Normalizes and scales constituent weights based on their manually assigned theme exposure scores.
  3. **Manual weight**: Allows custom percentage weights for each constituent, validated to ensure they sum to exactly 100%.
* **Historical Analysis**: Backtests custom definitions and renders interactive Plotly charts comparing their performance against QQQ and NVDA benchmarks across 1M, 3M, 6M, 1Y, and historical timeframes.
* **Deep Dives**: Displays the constituent weights table, historical theme concentration breakdown, and top performance contributors over the past 90 days.
