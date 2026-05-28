# AI Infra Watcher

Local-first Streamlit app for monitoring AI and data-center infrastructure stocks.

## Quick start

1. Create and activate a Python 3.12 virtual environment.
2. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

3. Initialize SQLite database:

```bash
python3 scripts/init_db.py
```

4. Run the app:

```bash
streamlit run app/main.py
```

5. Run tests:

```bash
python3 -m pytest
```
