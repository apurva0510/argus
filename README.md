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
- Optional API keys may stay blank.

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

Implemented through Phase 10-style MVP workflow:

- SQLite schema and seed data
- yfinance price ingestion
- daily metrics
- Dashboard, Watchlists, Company Detail, Pullback Finder, and News/Filings/Alerts pages
- RSS/GDELT news ingestion
- SEC EDGAR filings ingestion
- opportunity scoring
- email alert rules and deduplication
- daily refresh orchestration

Still pending:

- AI Infra Core Index implementation and charting
- fundamentals refresh
- earnings refresh provider
