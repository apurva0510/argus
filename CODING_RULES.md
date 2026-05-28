# CODING_RULES.md

## Product
This is a lightweight Streamlit research app for two users. It is not a trading platform.

## Constraints
- Prefer simple, local-first code
- Use free data sources first
- Do not require paid APIs
- Do not require Postgres for MVP
- Do not require Docker for MVP
- Do not add trade execution
- Do not store brokerage credentials
- Keep code modular and testable

## Stack
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

## Data Rules
- Price ingestion must be idempotent
- Use adjusted close for return calculations unless explicitly documented otherwise
- Store raw provider/source name on ingested rows
- Do not silently overwrite manual notes or watch statuses
- All alert events must have dedupe keys
- All jobs must write to job_runs

## Streamlit Rules
- Do not run long ingestion jobs automatically on page load
- Use buttons or CLI scripts for refreshes
- Use st.cache_data for query results
- Use st.cache_resource for DB connections
- Show stale data warnings

## API Rules
- yfinance is default market data source
- SEC calls must include SEC_USER_AGENT
- SEC calls must be rate-limited
- Optional providers must only activate when API keys exist
- Missing optional API keys must not break the app

## Testing Rules
- Add tests for indicators
- Add tests for scoring
- Add tests for alert deduplication
- Add tests for index calculations
- Prefer fixture-based tests for external data clients