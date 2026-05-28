# Argus

Local-first Streamlit app for monitoring AI and data-center infrastructure stocks.

## Quick start

1. Create and activate a virtual environment with Python 3.12.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3. Initialize SQLite database:

```bash
python -m argus.core.init_db
```

4. Seed companies, themes, and watchlists:

```bash
python -m argus.core.seed_companies
```

5. Run the app:

```bash
streamlit run app/main.py
```

6. Run tests:

```bash
python -m pytest
```
