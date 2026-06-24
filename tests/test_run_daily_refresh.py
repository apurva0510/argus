from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import JobRun
from argus.pipelines.run_daily_refresh import build_daily_refresh_steps, run_daily_refresh


def _patch_session(sqlite_engine, monkeypatch):
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    return db_module


def test_run_daily_refresh_records_job_and_aggregates_steps(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    result = run_daily_refresh(
        steps=[
            ("step_one", lambda: {"status": "success", "rows_read": 2, "rows_written": 1}),
            ("step_two", lambda: {"status": "success", "rows_read": 3, "rows_written": 4}),
        ]
    )

    assert result["status"] == "success"
    assert result["rows_read"] == 5
    assert result["rows_written"] == 5
    assert set(result["results"]) == {"step_one", "step_two"}

    with db_module.session_scope() as session:
        job = session.query(JobRun).filter(JobRun.job_name == "run_daily_refresh").one()
        assert job.status == "success"
        assert job.rows_read == 5
        assert job.rows_written == 5
        assert job.error_text is None


def test_run_daily_refresh_reports_partial_success(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    result = run_daily_refresh(
        steps=[
            ("ok", lambda: {"status": "success", "rows_read": 1, "rows_written": 1}),
            (
                "bad",
                lambda: {
                    "status": "failed",
                    "rows_read": 2,
                    "rows_written": 0,
                    "error_text": "boom",
                },
            ),
        ]
    )

    assert result["status"] == "partial_success"
    assert "bad: boom" in result["error_text"]

    with db_module.session_scope() as session:
        job = session.query(JobRun).filter(JobRun.job_name == "run_daily_refresh").one()
        assert job.status == "partial_success"
        assert job.error_text == "bad: boom"


def test_run_daily_refresh_preserves_partial_success_step(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    result = run_daily_refresh(
        steps=[
            (
                "refresh_filings",
                lambda: {
                    "status": "partial_success",
                    "rows_read": 0,
                    "rows_written": 0,
                    "not_found_symbols": ["AAA"],
                    "error_text": "Failed symbols: AAA",
                },
            )
        ]
    )

    assert result["status"] == "partial_success"

    with db_module.session_scope() as session:
        job = session.query(JobRun).filter(JobRun.job_name == "run_daily_refresh").one()
        assert job.status == "partial_success"


def test_build_daily_refresh_steps_skips_filings_without_sec_user_agent(monkeypatch) -> None:
    from argus.pipelines import run_daily_refresh as module

    monkeypatch.setattr(module.settings, "sec_user_agent", "")

    step_names = [
        name
        for name, _ in build_daily_refresh_steps(
            include_news=False,
            include_filings=True,
            include_alerts=False,
            include_fundamentals=False,
            include_earnings=False,
            include_macro=False,
        )
    ]

    assert step_names == [
        "refresh_intraday_close_markers",
        "refresh_prices",
        "compute_daily_metrics",
        "compute_opportunity_scores",
        "refresh_index",
        "compute_signals",
        "generate_theses",
    ]


def test_build_daily_refresh_steps_refreshes_one_day_intraday_close_markers(
    monkeypatch,
) -> None:
    from argus.pipelines import run_daily_refresh as module

    calls = []

    def fake_refresh_prices(period=None, *, interval="1d"):
        calls.append({"period": period, "interval": interval})
        return {"status": "success", "rows_read": 0, "rows_written": 0}

    monkeypatch.setattr(module, "refresh_prices", fake_refresh_prices)

    steps = build_daily_refresh_steps(
        period="2y",
        include_news=False,
        include_filings=False,
        include_alerts=False,
        include_fundamentals=False,
        include_earnings=False,
        include_macro=False,
    )
    dict(steps)["refresh_intraday_close_markers"]()

    assert calls == [{"period": "1d", "interval": "15m"}]


def test_build_daily_refresh_steps_includes_new_pipelines(monkeypatch) -> None:
    from argus.pipelines import run_daily_refresh as module

    monkeypatch.setattr(module.settings, "sec_user_agent", "")
    monkeypatch.setattr(module.settings, "fred_api_key", "")

    step_names = [
        name
        for name, _ in build_daily_refresh_steps(
            include_news=False,
            include_filings=False,
            include_alerts=False,
            include_fundamentals=True,
            include_earnings=True,
        )
    ]

    assert step_names == [
        "refresh_intraday_close_markers",
        "refresh_prices",
        "refresh_macro",
        "refresh_fundamentals",
        "compute_valuation_peers",
        "refresh_earnings",
        "compute_daily_metrics",
        "compute_opportunity_scores",
        "refresh_index",
        "compute_signals",
        "generate_theses",
    ]


def test_build_daily_refresh_steps_with_all_enabled(monkeypatch) -> None:
    from argus.pipelines import run_daily_refresh as module

    monkeypatch.setattr(module.settings, "sec_user_agent", "Argus/1.0 (test@example.com)")
    monkeypatch.setattr(module.settings, "fred_api_key", "test-key")

    step_names = [
        name
        for name, _ in build_daily_refresh_steps(
            include_news=False,
            include_filings=False,
            include_alerts=False,
            include_fundamentals=True,
            include_earnings=True,
            include_macro=True,
        )
    ]

    assert step_names == [
        "refresh_intraday_close_markers",
        "refresh_prices",
        "refresh_macro",
        "refresh_release_calendar",
        "refresh_capex",
        "refresh_fundamentals",
        "compute_valuation_peers",
        "refresh_earnings",
        "compute_daily_metrics",
        "compute_opportunity_scores",
        "refresh_index",
        "compute_signals",
        "generate_theses",
    ]


def test_build_daily_refresh_steps_syncs_ciks_before_filings(monkeypatch) -> None:
    from argus.pipelines import run_daily_refresh as module

    monkeypatch.setattr(module.settings, "sec_user_agent", "Argus/1.0 (test@example.com)")

    step_names = [
        name
        for name, _ in build_daily_refresh_steps(
            include_news=False,
            include_filings=True,
            include_alerts=False,
            include_fundamentals=False,
            include_earnings=False,
            include_macro=False,
        )
    ]

    assert step_names.index("refresh_ciks") < step_names.index("refresh_filings")
    assert step_names[step_names.index("refresh_filings") + 1] == "compute_signals"
    assert step_names[step_names.index("compute_signals") + 1] == "generate_theses"
    assert step_names.index("refresh_intraday_close_markers") == 0
    assert step_names.index("refresh_prices") == 1
