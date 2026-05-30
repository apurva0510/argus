# Argus

Local-first Streamlit app for monitoring AI and data-center infrastructure stocks.

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

3. Initialize SQLite database:

```bash
python3 scripts/init_db.py
```

4. Seed companies, themes, and watchlists:

```bash
python3 scripts/seed_companies.py
```

5. Backfill prices and compute daily metrics:

```bash
python3 scripts/backfill_prices.py --period 2y
python3 scripts/compute_metrics.py
```

6. Run the app:

```bash
.venv/bin/streamlit run app/main.py
```

7. Run tests:

```bash
python3 -m pytest
```
