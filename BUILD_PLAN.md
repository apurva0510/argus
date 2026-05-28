# Argus: Updated Streamlit Build Plan for Codex

## 1. Product Summary

Build a lightweight Streamlit application called **Argus**.

The app is designed for two users:

1. Developer/admin: me
2. Primary user: my dad

The purpose is to monitor stocks in sectors linked to AI infrastructure and data centers that may not have fully run up in the AI trade yet. The app should act as a one-stop shop for research, monitoring, pullback detection, news, filings, and alerts.

The app is not meant to be a trading execution platform. It is a research and decision-support tool.

Primary question the app should answer:

> Which AI and data-center infrastructure stocks are becoming interesting right now?

Secondary questions:

> Why is this stock moving?
> Is this a high-quality pullback or a broken story?
> Are there filings, earnings, or news catalysts?
> Should I add this stock to a closer watchlist?

## 2. Product Constraints

### Users

Only two people will use the app:

- Me, mostly during development
- My dad, as the main end user

### Budget

Target budget:

```text
$0/month
```

Acceptable budget:

```text
$5 to $10/month
```

Hard ceiling:

```text
$20 to $30/month only if absolutely necessary
```

Do not design around paid APIs by default. The app should work primarily with free sources.

### Scope Philosophy

Build a useful family research tool first.

Avoid:

- enterprise-grade data engineering
- expensive APIs
- complex cloud infrastructure
- multi-user role-based authentication
- real-time trading data
- overly complex macro ingestion
- advanced ML sentiment
- overbuilt index construction

Prioritize:

- watchlists
- stock monitoring
- pullback detection
- simple technical metrics
- basic valuation snapshots
- SEC filings
- news aggregation
- earnings dates
- alerting
- manual notes

## 3. Recommended MVP Architecture

Use a local-first architecture:

```text
Streamlit UI
   |
SQLite database
   |
Python refresh scripts
   |
Free data sources
```

Use SQLite as the application database.

Use local files for raw data snapshots:

```text
data/raw/
data/lake/
data/exports/
```

Use Parquet only where helpful for historical analytical snapshots. Do not overbuild a data lake in the MVP.

## 4. Recommended Data Source Strategy

### MVP Sources

Start with these:

```text
yfinance
SEC EDGAR
Yahoo Finance RSS
Google News RSS
GDELT
Manual seed data
```

### Optional Free API Keys

Add only after the base app works:

```text
Finnhub free tier
FRED
EIA
Alpha Vantage
Twelve Data
```

### Avoid at MVP

Do not build around these initially:

```text
Polygon
NewsAPI paid plan
Bloomberg
FactSet
Refinitiv
complex intraday feeds
paid fundamentals APIs
```

### Data Source Priority

Use this order:

1. yfinance for prices, historical bars, simple fundamentals, and earnings dates where available
2. SEC EDGAR for filings and company disclosure
3. RSS/GDELT for news headlines
4. Manual theme scores and notes
5. Optional API providers only when free sources fail

## 5. Initial Stock Universe

Seed the app with grouped AI infrastructure sectors.

### AI Capex Benchmarks

```text
NVDA
MSFT
AMZN
GOOGL
META
QQQ
```

### Power and Grid

```text
ETN
GEV
PWR
ABBNY
SBGSY
SIEGY
HUBB
```

### Cooling and Data Center Infrastructure

```text
VRT
TT
CARR
JCI
```

### Optical, Fiber, and Networking

```text
CIEN
GLW
COHR
LITE
NOK
CSCO
ANET
```

### Semiconductor Equipment and Advanced Packaging

```text
AMAT
KLAC
LRCX
ASML
ONTO
TER
```

### Energy, Nuclear, and Utilities

```text
CEG
VST
NEE
CCJ
SMR
```

### Data Center REITs

```text
EQIX
DLR
```

### Optional Aggressive AI Infrastructure Names

```text
ALAB
CRDO
```

Each company should have:

- ticker
- company name
- sector bucket
- theme tags
- priority level
- watch status
- manual notes
- theme exposure score

## 6. MVP Pages

Build five main pages.

### Page 1: Dashboard

Purpose:

Give my dad a simple daily overview.

Show:

- AI Infra Index performance
- top gainers
- top losers
- biggest one-week pullbacks
- stocks near 52-week highs
- stocks down meaningfully from 52-week highs
- recent news
- recent SEC filings
- upcoming earnings
- active alerts
- stale data warnings

Main question:

> Is anything interesting happening today?

### Page 2: Watchlists

Purpose:

Organize stocks by sector and watch status.

Required features:

- system watchlists by theme
- manual custom watchlists
- status field:
  - Ignore
  - Watch
  - High Priority
  - Owned
- notes field
- editable theme score
- sortable table

Table columns:

```text
Ticker
Company
Theme
Watch Status
Price
1D %
1W %
1M %
3M %
YTD %
52W High
Drawdown from 52W High
50DMA
200DMA
RSI 14
Market Cap
Forward P/E if available
Notes
```

### Page 3: Company Detail

Purpose:

Let the user research one stock deeply.

Show:

- price chart
- relative performance vs QQQ
- relative performance vs NVDA
- relative performance vs AI Infra Index
- moving averages
- RSI
- 52-week high/low
- drawdown from high
- valuation snapshot
- latest news
- latest SEC filings
- upcoming earnings
- user notes
- alert history
- watch status editor

Main question:

> Is this stock worth researching further?

### Page 4: Pullback Finder

Purpose:

This is the core trading guide page.

Find stocks that have pulled back but may still have strong AI infrastructure exposure.

Flag stocks using criteria like:

```text
Drawdown from 52-week high >= 10%
RSI below 45
Price still above or near 200DMA
Positive relative strength vs QQQ over 3M or 6M
High theme exposure score
No obvious negative filing/news flag
```

Create an explainable Opportunity Score.

Example formula:

```text
Opportunity Score =
Theme Exposure Score
+ Pullback Score
+ Technical Setup Score
+ Relative Strength Score
+ Catalyst Score
- Hype Risk Score
- Breakdown Risk Score
```

Each flagged stock should include a plain-English explanation.

Example:

```text
VRT flagged because:
- Down 18% from 52-week high
- RSI below 40
- Still above 200DMA
- High AI cooling/data-center exposure
- Relative performance vs QQQ remains positive over 6 months
```

Add filters:

- sector
- watch status
- minimum drawdown
- RSI range
- above/below 200DMA
- theme score
- market cap range

### Page 5: News, Filings, and Alerts

Purpose:

Combine catalysts and monitoring.

Sections:

1. News feed
2. SEC filings
3. Upcoming earnings
4. Alert rules
5. Alert history

News filters:

- ticker
- theme
- source
- keyword
- date range

Important keywords:

```text
AI infrastructure
data center
datacenter
hyperscaler
capex
capital expenditure
power demand
grid
transformer
switchgear
liquid cooling
cooling
nuclear
natural gas
interconnection
backlog
supply constraint
orders
guidance
earnings
```

SEC filing types to track:

```text
10-K
10-Q
8-K
6-K
20-F
40-F
```

Alert types:

```text
Price below target
Price above target
1D move greater than X%
Drawdown from 52W high greater than X%
RSI below threshold
Price crosses 50DMA
Price crosses 200DMA
New SEC filing
News keyword match
Earnings within X days
Stock enters Pullback Finder
```

Start with email alerts only.

Optional later:

```text
Telegram bot
SMS
Slack webhook
```

## 7. Data Model

Use SQLAlchemy with SQLite.

### Tables

```text
companies
themes
company_theme_exposure
watchlists
watchlist_items
price_bars
daily_metrics
fundamentals_snapshot
news_items
news_mentions
sec_filings
earnings_events
alerts
alert_events
user_notes
job_runs
app_settings
```

### companies

Fields:

```text
id
symbol
name
exchange
sector
industry
country
cik
is_active
is_benchmark
is_hyperscaler
created_at
updated_at
```

### themes

Fields:

```text
id
code
name
description
parent_theme_id
```

Example themes:

```text
power_grid
cooling
optical_networking
semicap
advanced_packaging
nuclear_power
data_center_reit
construction
hyperscaler_capex
benchmark
```

### company_theme_exposure

Fields:

```text
id
company_id
theme_id
exposure_score
confidence
source
notes
as_of_date
```

Use a 0 to 5 score.

### watchlists

Fields:

```text
id
name
description
is_system
created_at
updated_at
```

### watchlist_items

Fields:

```text
id
watchlist_id
company_id
watch_status
sort_order
notes
created_at
updated_at
```

watch_status values:

```text
ignore
watch
high_priority
owned
```

### price_bars

Fields:

```text
id
company_id
date
open
high
low
close
adj_close
volume
provider
interval
created_at
```

Unique key:

```text
company_id + date + provider + interval
```

### daily_metrics

Fields:

```text
id
company_id
date
return_1d
return_1w
return_1m
return_3m
return_6m
return_ytd
ma_50
ma_200
rsi_14
high_52w
low_52w
drawdown_52w
distance_from_50dma
distance_from_200dma
relative_return_vs_qqq_1m
relative_return_vs_qqq_3m
relative_return_vs_nvda_1m
relative_return_vs_nvda_3m
volatility_20d
opportunity_score
created_at
```

### fundamentals_snapshot

Fields:

```text
id
company_id
as_of_date
market_cap
enterprise_value
trailing_pe
forward_pe
price_to_sales
ev_to_sales
ev_to_ebitda
revenue_growth
gross_margin
operating_margin
free_cash_flow
provider
created_at
```

### news_items

Fields:

```text
id
published_at
title
summary
url
source_name
provider
sentiment_score
relevance_score
created_at
```

### news_mentions

Fields:

```text
id
news_id
company_id
ticker
is_primary_match
matched_keywords
```

### sec_filings

Fields:

```text
id
company_id
accession_no
form
filing_date
acceptance_datetime
primary_doc_url
filing_detail_url
is_new
created_at
```

### earnings_events

Fields:

```text
id
company_id
event_date
fiscal_period
eps_estimate
eps_actual
revenue_estimate
revenue_actual
source
created_at
```

### alerts

Fields:

```text
id
name
rule_type
company_id
watchlist_id
config_json
channel
destination
is_enabled
last_triggered_at
created_at
updated_at
```

### alert_events

Fields:

```text
id
alert_id
triggered_at
company_id
event_type
payload_json
delivery_status
dedupe_key
created_at
```

### user_notes

Fields:

```text
id
company_id
note_text
note_type
created_by
created_at
updated_at
```

### job_runs

Fields:

```text
id
job_name
started_at
finished_at
status
rows_read
rows_written
error_text
created_at
```

## 8. Repository Structure

Use this structure:

```text
argus/
  README.md
  pyproject.toml
  requirements.txt
  .env.example
  .gitignore

  app/
    main.py
    pages/
      dashboard.py
      watchlists.py
      company_detail.py
      pullback_finder.py
      news_filings_alerts.py
    components/
      charts.py
      tables.py
      metrics.py
      filters.py

  argus/
    core/
      settings.py
      logging.py
      db.py
      models.py
      seed.py

    sources/
      yfinance_client.py
      sec_client.py
      news_rss_client.py
      gdelt_client.py
      finnhub_client.py

    pipelines/
      refresh_prices.py
      refresh_fundamentals.py
      refresh_filings.py
      refresh_news.py
      refresh_earnings.py
      compute_metrics.py
      compute_scores.py
      run_alerts.py
      run_daily_refresh.py

    analytics/
      indicators.py
      scoring.py
      index_builder.py
      relative_strength.py

    alerts/
      rules.py
      email_delivery.py
      formatting.py

    services/
      company_service.py
      watchlist_service.py
      dashboard_service.py
      alert_service.py

  data/
    app.db
    raw/
    lake/
    exports/

  scripts/
    init_db.py
    seed_companies.py
    backfill_prices.py
    run_daily_refresh.py
    run_alerts.py

  tests/
    test_indicators.py
    test_scoring.py
    test_alert_rules.py
    test_seed_data.py
```

## 9. Technical Stack

Use:

```text
Python 3.12
Streamlit
SQLite
SQLAlchemy
Pandas
NumPy
Plotly
yfinance
httpx
feedparser
pydantic
python-dotenv
APScheduler optional
pytest
ruff
```

Optional:

```text
polars
pyarrow
finnhub-python
newspaper3k
```

Do not add heavy dependencies unless needed.

## 10. MVP Implementation Phases

### Phase 1: Scaffold and Database

Goal:

Create the repo, app shell, database models, and seed data.

Deliverables:

- Streamlit multipage app
- SQLite database connection
- SQLAlchemy models
- seed company universe
- seed themes
- seed watchlists
- basic navigation
- README with setup instructions

Codex prompt:

```text
Build the initial scaffold for a local-first Streamlit app called Argus.

Requirements:
- Use Python 3.12
- Use Streamlit for the UI
- Use SQLite and SQLAlchemy for storage
- Create a package named argus
- Create pages: Dashboard, Watchlists, Company Detail, Pullback Finder, News Filings Alerts
- Create SQLAlchemy models for companies, themes, company_theme_exposure, watchlists, watchlist_items, price_bars, daily_metrics, fundamentals_snapshot, news_items, news_mentions, sec_filings, earnings_events, alerts, alert_events, user_notes, job_runs
- Add scripts/init_db.py
- Add scripts/seed_companies.py
- Seed the database with AI infrastructure stocks grouped by sector
- Keep the UI functional even before live data is loaded
```

### Phase 2: Price Ingestion and Metrics

Goal:

Use yfinance to fetch daily prices and compute metrics.

Deliverables:

- yfinance client
- price backfill script
- daily refresh script
- metrics computation
- dashboard table populated with real data

Metrics:

```text
1D return
1W return
1M return
3M return
6M return
YTD return
50DMA
200DMA
RSI 14
52W high
52W low
drawdown from 52W high
distance from 50DMA
distance from 200DMA
relative return vs QQQ
relative return vs NVDA
20D volatility
```

Codex prompt:

```text
Implement price ingestion and daily metrics.

Requirements:
- Create sources/yfinance_client.py
- Fetch daily OHLCV data for all active companies
- Store data in price_bars
- Make ingestion idempotent
- Add scripts/backfill_prices.py
- Add pipelines/refresh_prices.py
- Add analytics/indicators.py with RSI, moving averages, returns, drawdown, volatility
- Add pipelines/compute_metrics.py to populate daily_metrics
- Compute relative returns vs QQQ and NVDA
- Add unit tests for the indicator functions
```

### Phase 3: Dashboard and Watchlists

Goal:

Make the app useful for daily review.

Deliverables:

- dashboard with KPI cards
- top movers
- pullback candidates
- watchlist tables
- editable notes and status
- stale data warnings

Codex prompt:

```text
Build the Dashboard and Watchlists pages.

Dashboard requirements:
- Show last refresh time
- Show AI Infra Index level
- Show 1D, 1W, 1M performance
- Show top 5 gainers and losers
- Show biggest drawdowns from 52W high
- Show stocks with RSI below 40
- Show upcoming earnings placeholder
- Show latest news placeholder
- Show latest filings placeholder

Watchlists requirements:
- Show sector-grouped watchlists
- Allow editing watch_status and notes
- Use st.data_editor
- Persist edits to SQLite
- Add filters for theme, watch status, and ticker
```

### Phase 4: Pullback Finder

Goal:

Create the core trade setup detection page.

Deliverables:

- opportunity scoring engine
- ranked pullback table
- explanation strings
- filters
- visual flags

Opportunity Score v1:

```text
Theme Exposure Score: 0 to 25
Pullback Score: 0 to 25
Technical Setup Score: 0 to 20
Relative Strength Score: 0 to 15
Catalyst Score: 0 to 10
Watchlist Priority Score: 0 to 5
Risk Penalty: -30 to 0
```

Score components:

```text
Theme exposure based on manual 0 to 5 score
Pullback based on drawdown from 52W high
Technical setup based on RSI and 200DMA distance
Relative strength based on 3M relative return vs QQQ
Catalyst score based on recent news, filings, or upcoming earnings
Risk penalty if price is far below 200DMA or recent decline is extreme
```

Codex prompt:

```text
Build the Pullback Finder page and scoring engine.

Requirements:
- Create analytics/scoring.py
- Compute an opportunity_score for each company
- Store latest score in daily_metrics
- Rank companies by opportunity_score
- Add explanation strings for each score
- Add filters for sector, theme, watch status, minimum drawdown, RSI range, and above/below 200DMA
- Display a table of candidates with score, price metrics, theme, watch status, and explanation
- Add tests for scoring logic
```

### Phase 5: Company Detail Page

Goal:

Allow deeper research into one ticker.

Deliverables:

- ticker selector
- price chart
- relative performance chart
- metric cards
- valuation snapshot
- news feed
- filings feed
- notes editor
- alerts linked to company

Codex prompt:

```text
Build the Company Detail page.

Requirements:
- Add ticker selector
- Show price chart using Plotly
- Show relative performance vs QQQ, NVDA, and AI Infra Index
- Show metrics: price, 1D, 1M, YTD, RSI, 52W drawdown, 50DMA, 200DMA
- Show fundamentals snapshot if available
- Show latest news for the ticker
- Show latest SEC filings for the ticker
- Add a notes editor backed by user_notes
- Add watch_status editor backed by watchlist_items
```

### Phase 6: News and SEC Filings

Goal:

Add catalyst monitoring using free sources.

Deliverables:

- SEC client
- RSS/GDELT news client
- keyword tagging
- news and filings page
- new filing detection

Codex prompt:

```text
Implement news and SEC filing ingestion.

Requirements:
- Create sources/sec_client.py
- Use SEC submissions API by CIK
- Always include a configurable User-Agent
- Rate limit SEC calls to no more than 8 requests per second
- Store filings in sec_filings
- Track 10-K, 10-Q, 8-K, 6-K, 20-F, 40-F
- Create sources/news_rss_client.py using feedparser
- Create sources/gdelt_client.py using httpx
- Fetch news for tracked tickers and AI infrastructure keywords
- Store news in news_items
- Store ticker links in news_mentions
- Add keyword tags
- Add a News, Filings, and Alerts page with filters
```

### Phase 7: Alerts

Goal:

Send useful notifications when stocks become interesting.

Deliverables:

- alert rule definitions
- alert runner
- email delivery
- deduplication
- alert history

Start with email only.

Alert rules:

```text
price_below
price_above
daily_move_gt
drawdown_52w_gt
rsi_below
crossed_50dma
crossed_200dma
new_sec_filing
news_keyword_match
earnings_within_days
entered_pullback_zone
```

Codex prompt:

```text
Build a simple alerting system.

Requirements:
- Create alerts/rules.py
- Create alerts/email_delivery.py
- Create pipelines/run_alerts.py
- Read active alerts from the alerts table
- Evaluate rules against latest daily_metrics, sec_filings, news_items, and earnings_events
- Store triggered events in alert_events
- Add dedupe_key to prevent duplicate alerts within 24 hours
- Send email using SMTP credentials from environment variables
- Add UI to create, enable, disable, and view alerts
```

### Phase 8: AI Infra Index

Goal:

Create a simple custom index for comparison.

Do not overbuild an index lab in MVP. Start with one default index.

Index name:

```text
AI Infra Core Index
```

Weighting v1:

```text
Equal weight across selected AI infrastructure names
Exclude benchmarks like NVDA, QQQ, MSFT, AMZN, GOOGL, META from the supplier index unless explicitly included
Base value: 100
Base date: earliest common available date
```

Deliverables:

- index builder
- index level chart
- relative performance vs QQQ and NVDA
- index contribution table

Codex prompt:

```text
Implement a simple AI Infra Core Index.

Requirements:
- Create analytics/index_builder.py
- Build an equal-weight index using selected non-benchmark AI infrastructure stocks
- Base index at 100
- Store or compute index levels from price_bars
- Show index chart on Dashboard
- Show relative performance vs QQQ and NVDA
- Show top contributors over 1M, 3M, and YTD
- Keep index construction simple and transparent
```

### Phase 9: Optional API Upgrade Layer

Goal:

Add paid/free API providers only after the MVP works.

Do not require these for the core app.

Provider order:

1. yfinance default
2. Finnhub optional
3. Twelve Data optional
4. Alpha Vantage optional fallback

Codex prompt:

```text
Add an optional market data provider abstraction.

Requirements:
- Create a provider interface for price data and fundamentals
- Keep yfinance as the default provider
- Add optional Finnhub support if FINNHUB_API_KEY exists
- Add optional Twelve Data support if TWELVE_DATA_API_KEY exists
- Add optional Alpha Vantage support if ALPHA_VANTAGE_API_KEY exists
- If optional keys are missing, app should continue working with yfinance
- Add provider status to the Data Health section
```

## 11. Scheduling

For MVP, use manual refresh buttons and CLI scripts.

Commands:

```bash
python scripts/init_db.py
python scripts/seed_companies.py
python scripts/backfill_prices.py
python scripts/run_daily_refresh.py
python scripts/run_alerts.py
streamlit run app/main.py
```

Later options:

### Local Cron

Use local cron for daily refresh.

### GitHub Actions

Use GitHub Actions for scheduled refresh if the app is deployed and the database is accessible.

### APScheduler

Use APScheduler only for local development or a simple always-on deployment.

Do not make Streamlit itself responsible for long-running background jobs in the MVP.

## 12. Deployment Plan

### Stage 1: Local Only

Run locally first.

```bash
streamlit run app/main.py
```

Best for development and early testing with my dad.

### Stage 2: Streamlit Community Cloud

Use only if persistence is acceptable or if the app reads from a committed/generated SQLite file.

Potential issue:

SQLite persistence may be awkward on Streamlit Community Cloud.

### Stage 3: Cheap VPS or Simple PaaS

Use only once the app is valuable.

Good options:

```text
Railway
Render
Fly.io
DigitalOcean
Hetzner
Google Cloud Run
Heroku Eco
```

Expected cost:

```text
$5 to $10/month
```

Only consider $20 to $30/month if:

- free data sources are too unreliable
- hosted persistence is needed
- alerts must run reliably
- the app becomes part of a regular family investment workflow

## 13. Security

Implement basic security only.

Requirements:

- simple shared password using environment variable
- no user registration
- no OAuth
- no role-based access control
- store API keys in `.env` or Streamlit secrets
- never commit secrets
- keep SMTP credentials in environment variables
- do not store brokerage credentials
- do not execute trades from the app

Environment variables:

```text
APP_PASSWORD
DATABASE_URL
SEC_USER_AGENT
EMAIL_HOST
EMAIL_PORT
EMAIL_USERNAME
EMAIL_PASSWORD
EMAIL_FROM
EMAIL_TO
FINNHUB_API_KEY
ALPHA_VANTAGE_API_KEY
TWELVE_DATA_API_KEY
```

## 14. Testing Plan

Add tests for the logic that matters.

Required tests:

```text
test_indicators.py
test_scoring.py
test_alert_rules.py
test_index_builder.py
test_seed_data.py
```

Test:

- RSI calculation
- moving averages
- returns
- 52W drawdown
- opportunity score
- alert deduplication
- index calculation
- seed data loads correctly

Do not overbuild UI tests in MVP.

## 15. Data Health

Add a small data health panel.

Show:

```text
Last price refresh
Last metrics computation
Last news refresh
Last filings refresh
Number of active companies
Number of stale tickers
Provider status
Latest failed job
```

Use `job_runs` as the source of truth.

## 16. MVP Success Criteria

The MVP is successful if my dad can:

1. Open the app
2. See which AI infrastructure sectors are moving
3. Identify meaningful pullbacks
4. Research one ticker quickly
5. Read recent news and filings
6. See upcoming earnings
7. Add notes
8. Mark stocks as Watch, High Priority, Owned, or Ignore
9. Receive email alerts when a stock becomes interesting

## 17. Features to Defer

Do not build these in MVP:

```text
Postgres
Docker production deployment
multi-user authentication
role-based permissions
full macro dashboard
FRED/BLS/BEA/Census ingestion
advanced sentiment model
FinBERT
LLM summarization
brokerage integration
trade execution
complex backtesting engine
custom index lab with many weighting modes
paid data vendor integration
SMS alerts
mobile app
```

## 18. Build Order for Codex

Use this order exactly:

```text
1. Repo scaffold and database
2. Seed company universe and themes
3. yfinance price ingestion
4. daily metrics computation
5. Dashboard page
6. Watchlists page
7. Pullback Finder page
8. Company Detail page
9. News and SEC filings ingestion
10. Alerts system
11. AI Infra Core Index
12. Optional provider abstraction
13. Deployment and documentation
```

## 19. Final Codex Master Prompt

Use this prompt to start the project:

```text
Build a local-first Streamlit application called Argus.

The app is for two users: me as the developer and my dad as the primary user. It should monitor AI and data-center infrastructure stocks that may not have fully run up in the AI trade.

The app should prioritize free data sources, low cost, and simplicity.

Core goals:
- Track AI infrastructure stocks by sector/theme
- Show price performance and technical metrics
- Detect high-quality pullbacks
- Show recent news and SEC filings
- Track upcoming earnings
- Support manual notes and watch statuses
- Send simple email alerts
- Build a simple AI Infra Core Index for comparison

Technical requirements:
- Python 3.12
- Streamlit
- SQLite
- SQLAlchemy
- Pandas
- NumPy
- Plotly
- yfinance
- httpx
- feedparser
- pydantic
- pytest
- ruff

Architecture:
- Streamlit for UI
- SQLite for app storage
- Python CLI scripts for ingestion and alerts
- yfinance as default market data source
- SEC EDGAR for filings
- RSS/GDELT for news
- Optional API providers only if keys are present

Do not require paid APIs.
Do not require Postgres.
Do not require Docker for MVP.
Do not build trading execution.
Do not build enterprise authentication.

Build in phases:
1. Scaffold repo and database
2. Seed companies and themes
3. Ingest prices with yfinance
4. Compute metrics
5. Build Dashboard
6. Build Watchlists
7. Build Pullback Finder
8. Build Company Detail
9. Add news and filings
10. Add alerts
11. Add simple AI Infra Core Index
12. Add optional provider abstraction

Make the code modular, testable, and easy to extend.
```

## 20. MVP Definition

The MVP is not a perfect financial terminal.

The MVP is:

> A low-cost, local-first Streamlit research dashboard that helps my dad monitor AI infrastructure stocks, spot pullbacks, understand catalysts, and receive simple alerts.

Everything else is secondary.