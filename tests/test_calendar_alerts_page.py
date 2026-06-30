import importlib

import pandas as pd


calendar_alerts_page = importlib.import_module("app.pages.6_Calendar_Alerts")


def test_historical_post_earnings_moves_are_signed(monkeypatch) -> None:
    captured_query = ""

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Engine:
        def connect(self):
            return Connection()

    def fake_read_sql_query(query, _connection):
        nonlocal captured_query
        captured_query = str(query)
        return pd.DataFrame(
            {"symbol": ["NVDA", "MU"], "avg_move": [0.075, -0.042]}
        )

    calendar_alerts_page.load_historical_post_earnings_moves.clear()
    monkeypatch.setattr(calendar_alerts_page, "get_db_engine", lambda: Engine())
    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    result = calendar_alerts_page.load_historical_post_earnings_moves()

    assert result == {"NVDA": 0.075, "MU": -0.042}
    assert "AVG(cis.return_event_to_p1)" in captured_query
    assert "AVG(ABS(" not in captured_query
