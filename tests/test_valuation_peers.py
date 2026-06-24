from datetime import date

import pytest
from sqlalchemy.orm import Session

from argus.analytics.valuation import (
    VALUATION_METRICS,
    build_peer_rows,
    compute_ev_sales_to_growth,
    valuation_metric_label,
)
from argus.core.models import (
    Company,
    CompanyThemeExposure,
    FundamentalsSnapshot,
    JobRun,
    Theme,
    ValuationPeerSnapshot,
)
from argus.pipelines.compute_valuation_peers import compute_valuation_peers


def test_compute_ev_sales_to_growth_requires_positive_inputs() -> None:
    assert compute_ev_sales_to_growth(6.0, 0.3) == pytest.approx(20.0)
    assert compute_ev_sales_to_growth(6.0, 0.0) is None
    assert compute_ev_sales_to_growth(None, 0.3) is None


def test_all_valuation_metrics_have_display_labels() -> None:
    for metric_name in VALUATION_METRICS:
        assert valuation_metric_label(metric_name) != metric_name


def test_build_peer_rows_flags_relative_valuation() -> None:
    fundamentals = [
        {"company_id": 1, "as_of_date": date(2026, 1, 1), "ev_to_sales": 2.0},
        {"company_id": 2, "as_of_date": date(2026, 1, 1), "ev_to_sales": 4.0},
        {"company_id": 3, "as_of_date": date(2026, 1, 1), "ev_to_sales": 8.0},
        {"company_id": 4, "as_of_date": date(2026, 1, 1), "ev_to_sales": 16.0},
    ]
    memberships = [
        {"company_id": 1, "peer_group_type": "sector", "peer_group_key": "Power"},
        {"company_id": 2, "peer_group_type": "sector", "peer_group_key": "Power"},
        {"company_id": 3, "peer_group_type": "sector", "peer_group_key": "Power"},
        {"company_id": 4, "peer_group_type": "sector", "peer_group_key": "Power"},
    ]

    rows = [
        row for row in build_peer_rows(fundamentals, memberships)
        if row.metric_name == "ev_to_sales"
    ]

    assert [row.valuation_flag for row in rows] == ["cheap", "neutral", "neutral", "stretched"]
    assert rows[0].peer_count == 3
    assert rows[0].peer_median == pytest.approx(8.0)
    assert rows[2].peer_median == pytest.approx(4.0)
    assert rows[2].premium_discount_pct == pytest.approx(1.0)


def test_compute_valuation_peers_is_idempotent(sqlite_engine, db_session: Session) -> None:
    theme = Theme(code="power", name="Power")
    companies = [
        Company(symbol="AAA", name="AAA", sector="Power"),
        Company(symbol="BBB", name="BBB", sector="Power"),
        Company(symbol="CCC", name="CCC", sector="Power"),
        Company(symbol="DDD", name="DDD", sector="Power"),
    ]
    db_session.add(theme)
    db_session.add_all(companies)
    db_session.flush()
    for idx, company in enumerate(companies, start=1):
        db_session.add(
            CompanyThemeExposure(
                company_id=company.id,
                theme_id=theme.id,
                exposure_score=float(idx),
            )
        )
        db_session.add(
            FundamentalsSnapshot(
                company_id=company.id,
                as_of_date=date(2026, 1, 1),
                ev_to_sales=float(idx * 2),
                forward_pe=float(idx * 10),
                provider="yfinance",
            )
        )
    db_session.commit()

    first = compute_valuation_peers()
    second = compute_valuation_peers()

    assert first["status"] == "success"
    assert second["status"] == "success"
    with Session(sqlite_engine) as session:
        snapshots = session.query(ValuationPeerSnapshot).all()
        jobs = session.query(JobRun).filter(JobRun.job_name == "compute_valuation_peers").all()
        assert len(jobs) == 2
        assert len(snapshots) == first["rows_written"]
        ev_rows = [
            row for row in snapshots
            if row.peer_group_type == "sector" and row.metric_name == "ev_to_sales"
        ]
        assert len(ev_rows) == 4
        assert {row.valuation_flag for row in ev_rows} == {"cheap", "neutral", "stretched"}
        assert {row.peer_count for row in ev_rows} == {3}
