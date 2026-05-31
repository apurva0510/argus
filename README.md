# Argus

Local-first Streamlit app for monitoring AI and data-center infrastructure stocks.

Argus is a research and monitoring tool for a small two-user workflow. It is not a trading platform and does not execute trades.

## Quick start

1. Create and activate a virtual environment with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

3. Create local environment config:

```bash
cp .env.example .env
```

Edit `.env` if you want SEC filings or email alerts:

- `SEC_USER_AGENT` is required for SEC EDGAR filing refreshes.
- `EMAIL_HOST`, `EMAIL_TO`, and optional SMTP credentials are used by email alerts.
- Optional API keys may stay blank (yfinance remains default and requires no credentials).
- Optional providers (`finnhub`, `twelvedata`, `alphavantage`) can be selected via the `MARKET_DATA_PROVIDER` env variable.
  
  > [!IMPORTANT]
  > Twelve Data and Alpha Vantage free tiers have strict rate limits and monthly quotas. Request interval pacing is automatically enforced to comply with limits. However, running full historical backfills (`--period 2y` or longer) frequently when utilizing Twelve Data can exhaust your monthly call volume credits.


4. Initialize SQLite database:

```bash
python3 scripts/init_db.py
```

5. Seed companies, themes, and watchlists:

```bash
python3 scripts/seed_companies.py
```

6. Backfill prices, compute daily metrics, and compute Pullback Finder scores:

```bash
python3 scripts/backfill_prices.py --period 2y
python3 scripts/compute_metrics.py
python3 scripts/compute_scores.py
```

7. Optionally refresh catalysts and alerts:

```bash
python3 scripts/refresh_news.py
python3 scripts/refresh_filings.py
python3 scripts/run_alerts.py
```

`refresh_news.py` is throttled by default and skips if a successful run happened recently. Use `--force` to bypass the throttle, or `--max-queries N` to limit broad news queries during testing. `refresh_filings.py` requires `SEC_USER_AGENT`.

8. Or run the daily refresh workflow:

```bash
python3 scripts/run_daily_refresh.py --period 2y
```

Useful flags:

```bash
python3 scripts/run_daily_refresh.py --skip-news
python3 scripts/run_daily_refresh.py --skip-filings
python3 scripts/run_daily_refresh.py --skip-alerts
```

The daily workflow runs prices, metrics, opportunity scores, optional news, optional SEC filings, and optional alerts. Each pipeline writes to `job_runs`.

9. Run the app:

```bash
.venv/bin/streamlit run app/main.py
```

10. Run tests:

```bash
.venv/bin/python -m pytest
```

Run lint:

```bash
.venv/bin/ruff check .
```

## Current scope

Implemented through Phase 11-style MVP workflow:

- SQLite schema and seed data
- yfinance price ingestion
- daily metrics
- Dashboard, Watchlists, Company Detail, Pullback Finder, and News/Filings/Alerts pages
- RSS/GDELT news ingestion
- SEC EDGAR filings ingestion
- opportunity scoring
- email alert rules and deduplication
- daily refresh orchestration
- AI Infra Core Index implementation, charting, and contributors mapping

Still pending:

- fundamentals refresh
- earnings refresh provider

## AI Infra Core Index Methodology

The custom **AI Infra Core Index** is built to monitor the collective performance of AI infrastructure and data-center supplier stocks.

### Weighting & Calculation
- **Equal Weighted**: The index is an equal-weighted average of all active constituent stocks.
- **Base Level**: Set to a base of 100.0. The chart on the Dashboard dynamically rebases the index level to 100 on the starting date of the selected timeframe for easy comparison.
- **Dynamic Rebalancing / Missing History**: IPOs (e.g. `GEV` or `ALAB`) and companies with missing historical price bars are handled gracefully. The daily index return is the average of daily returns of only those constituents that have valid price data on both the current and the previous trading day. This average return is then compounded daily to build the index level.

### Constituents & Exclusions
- **Constituents**: Selected active AI infrastructure and data-center supplier stocks.
- **Default Exclusions**: Benchmark-only and large hyperscaler names (`QQQ`, `NVDA`, `MSFT`, `AMZN`, `GOOGL`, `META`) and optional highly aggressive stocks (`ALAB`, `CRDO`) are excluded from the index calculation by default.
