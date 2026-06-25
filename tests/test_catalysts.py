import pytest
from datetime import date, datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

from argus.core.models import Company, PriceBar, EarningsEvent, SecFiling, CatalystEvent, CatalystImpactSnapshot
from argus.pipelines.refresh_catalysts import refresh_catalyst_impact


def test_refresh_catalysts_ingestion_and_impact(sqlite_engine, db_session: Session) -> None:
    # 1. Seed companies
    nvda = Company(symbol="NVDA", name="NVIDIA Corp.", is_active=True, is_benchmark=True, is_hyperscaler=False)
    msft = Company(symbol="MSFT", name="Microsoft Corp.", is_active=True, is_benchmark=True, is_hyperscaler=True)
    aapl = Company(symbol="AAPL", name="Apple Inc.", is_active=True, is_benchmark=False, is_hyperscaler=False)
    db_session.add_all([nvda, msft, aapl])
    db_session.flush()

    # 2. Seed price bars for all 3 companies (30 trading days starting 2026-01-01)
    # We set all prices to 100 for simplicity except NVDA which moves around earnings
    start_date = date(2026, 1, 1)
    for comp_id in [nvda.id, msft.id, aapl.id]:
        for i in range(40):
            d = start_date + timedelta(days=i)
            # NVDA drops by 10% on earnings day 2026-01-05 (index 4)
            price = 100.0
            if comp_id == nvda.id:
                if i < 4:
                    price = 100.0
                elif i == 4: # 2026-01-05
                    price = 90.0
                else:
                    price = 95.0

            bar = PriceBar(
                company_id=comp_id,
                date=d,
                bar_time=d,
                open=price,
                high=price,
                low=price,
                close=price,
                adj_close=price,
                provider="yfinance",
                interval="1d"
            )
            db_session.add(bar)

    # 3. Seed original earnings event for NVDA on 2026-01-05
    ee_nvda = EarningsEvent(
        company_id=nvda.id,
        event_date=date(2026, 1, 5),
        fiscal_period="Q4",
        eps_estimate=1.0,
        eps_actual=1.2,
        revenue_estimate=1000.0,
        revenue_actual=1100.0,
        source="yfinance"
    )
    db_session.add(ee_nvda)

    # Seed original earnings event for MSFT (hyperscaler) on 2026-01-06
    ee_msft = EarningsEvent(
        company_id=msft.id,
        event_date=date(2026, 1, 6),
        fiscal_period="Q2",
        eps_estimate=2.0,
        eps_actual=2.1,
        source="yfinance"
    )
    db_session.add(ee_msft)

    # Seed SEC filing for AAPL on 2026-01-08
    sf_aapl = SecFiling(
        company_id=aapl.id,
        accession_no="0000320193-26-000001",
        form="10-Q",
        filing_date=date(2026, 1, 8),
        acceptance_datetime=datetime(2026, 1, 8, 16, 0, 0),
        primary_doc_url="http://sec.gov/doc",
        filing_detail_url="http://sec.gov/detail"
    )
    db_session.add(sf_aapl)
    db_session.commit()

    # 4. Run catalyst impact pipeline
    res = refresh_catalyst_impact()

    # Verify return counts
    assert res["events_created"] > 0
    assert res["snapshots_updated"] > 0

    # 5. Assertions on Ingested Events
    # A. NVDA Earnings
    nvda_earnings_events = db_session.query(CatalystEvent).filter(
        CatalystEvent.company_id == nvda.id,
        CatalystEvent.event_type == "earnings"
    ).all()
    assert len(nvda_earnings_events) == 1
    assert nvda_earnings_events[0].date == date(2026, 1, 5)
    assert nvda_earnings_events[0].details["eps_actual"] == 1.2

    # B. Cross-stock NVDA Earnings created for AAPL and MSFT
    cross_nvda_aapl = db_session.query(CatalystEvent).filter(
        CatalystEvent.company_id == aapl.id,
        CatalystEvent.event_type == "nvda_earnings"
    ).one()
    assert cross_nvda_aapl.date == date(2026, 1, 5)

    cross_nvda_msft = db_session.query(CatalystEvent).filter(
        CatalystEvent.company_id == msft.id,
        CatalystEvent.event_type == "nvda_earnings"
    ).one()
    assert cross_nvda_msft.date == date(2026, 1, 5)

    # C. Cross-stock MSFT (hyperscaler) Earnings created for AAPL and NVDA
    cross_msft_aapl = db_session.query(CatalystEvent).filter(
        CatalystEvent.company_id == aapl.id,
        CatalystEvent.event_type == "hyperscaler_earnings"
    ).one()
    assert cross_msft_aapl.date == date(2026, 1, 6)
    assert cross_msft_aapl.details["trigger_symbol"] == "MSFT"

    # D. SEC 10-Q for AAPL
    aapl_filing_events = db_session.query(CatalystEvent).filter(
        CatalystEvent.company_id == aapl.id,
        CatalystEvent.event_type == "sec_10q"
    ).all()
    assert len(aapl_filing_events) == 1
    assert aapl_filing_events[0].date == date(2026, 1, 8)
    assert aapl_filing_events[0].details["accession_no"] == "0000320193-26-000001"

    # 6. Assertions on Snapshots / Calculations
    # For NVDA earnings event (2026-01-05):
    # NVDA price list index mapping:
    # 2026-01-05 is index 4 (adj_close = 90.0)
    # M1 (2026-01-04) is index 3 (adj_close = 100.0)
    # P1 (2026-01-06) is index 5 (adj_close = 95.0)
    # Expected M1-to-event return: (90.0 - 100.0) / 100.0 = -0.10 (-10.0%)
    # Expected event-to-P1 return: (95.0 - 90.0) / 90.0 = 5 / 90 = 0.055556 (+5.6%)
    nvda_event_id = nvda_earnings_events[0].id
    snap = db_session.query(CatalystImpactSnapshot).filter(
        CatalystImpactSnapshot.catalyst_event_id == nvda_event_id
    ).one()
    assert snap.return_m1_to_event == pytest.approx(-0.10)
    assert snap.return_event_to_p1 == pytest.approx(5.0 / 90.0)
