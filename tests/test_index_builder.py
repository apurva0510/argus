from datetime import date, timedelta
import pandas as pd
import pytest
from sqlalchemy.orm import Session
from argus.core.models import Company, CompanyThemeExposure, IndexDefinition, PriceBar, Theme
from argus.analytics.index_builder import (
    INDEX_MODE_EXPOSURE,
    INDEX_MODE_MANUAL,
    get_default_index_symbols,
    calculate_equal_weight_index,
    calculate_relative_performance,
    calculate_top_contributors,
    calculate_theme_concentration,
    calculate_weighted_index,
    create_index_definition,
    get_index_weights,
    validate_manual_weights,
)


def _seed_prices(session: Session, company_id: int, start_date: date, prices: list[float]) -> None:
    for offset, price in enumerate(prices):
        session.add(
            PriceBar(
                company_id=company_id,
                date=start_date + timedelta(days=offset),
                open=price,
                high=price,
                low=price,
                close=price,
                adj_close=price,
                volume=1000,
                provider="yfinance",
                interval="1d",
            )
        )


def test_get_default_index_symbols(db_session: Session) -> None:
    # Set up some active and inactive companies
    c1 = Company(symbol="ETN", name="Eaton", is_active=True, is_benchmark=False)
    c2 = Company(symbol="NVDA", name="NVIDIA", is_active=True, is_benchmark=True)
    c3 = Company(symbol="ALAB", name="Astera", is_active=True, is_benchmark=False)
    c4 = Company(symbol="VRT", name="Vertiv", is_active=False, is_benchmark=False)
    c5 = Company(symbol="IONQ", name="IonQ", is_active=True, is_benchmark=False)
    c6 = Company(symbol="IBM", name="IBM", is_active=True, is_benchmark=False)
    c7 = Company(symbol="INFQ", name="Infleqtion", is_active=True, is_benchmark=False)
    c8 = Company(symbol="RGTI", name="Rigetti", is_active=True, is_benchmark=False)
    c9 = Company(symbol="QBTS", name="D-Wave", is_active=True, is_benchmark=False)
    c10 = Company(symbol="QUBT", name="Quantum Computing", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2, c3, c4, c5, c6, c7, c8, c9, c10])
    db_session.flush()

    symbols = get_default_index_symbols(db_session)
    assert "ETN" in symbols
    assert "NVDA" not in symbols  # Excluded (Benchmark)
    assert "ALAB" not in symbols  # Excluded (Aggressive)
    assert "IONQ" not in symbols  # Excluded (Emerging Compute)
    assert "IBM" not in symbols  # Excluded (Emerging Compute)
    assert "INFQ" not in symbols  # Excluded (Emerging Compute)
    assert "RGTI" not in symbols  # Excluded (Emerging Compute)
    assert "QBTS" not in symbols  # Excluded (Emerging Compute)
    assert "QUBT" not in symbols  # Excluded (Emerging Compute)
    assert "VRT" not in symbols  # Excluded (Inactive)


def test_calculate_equal_weight_index(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    
    # Add constituents
    c1 = Company(symbol="A", name="A", is_active=True)
    c2 = Company(symbol="B", name="B", is_active=True)
    db_session.add_all([c1, c2])
    db_session.flush()

    # Ticker A: +10%, +0%
    # Ticker B: +5%, +10%
    _seed_prices(db_session, c1.id, start_date, [10.0, 11.0, 11.0])
    _seed_prices(db_session, c2.id, start_date, [20.0, 21.0, 23.1])
    db_session.flush()

    index_df = calculate_equal_weight_index(db_session, symbols=["A", "B"])

    assert not index_df.empty
    assert len(index_df) == 3
    assert index_df.iloc[0]["index_value"] == 100.0
    
    # Return on day 1: A = 10%, B = 5%. Average return = 7.5%
    # Index day 1: 100 * 1.075 = 107.5
    assert index_df.iloc[1]["index_value"] == pytest.approx(107.5)

    # Return on day 2: A = 0%, B = 10%. Average return = 5%
    # Index day 2: 107.5 * 1.05 = 112.875
    assert index_df.iloc[2]["index_value"] == pytest.approx(112.875)


def test_calculate_equal_weight_index_missing_history(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    
    # Constituent A is there for all 3 days
    # Constituent B is a new IPO, starts on day 1 (offset 1)
    c1 = Company(symbol="A", name="A", is_active=True)
    c2 = Company(symbol="B", name="B", is_active=True)
    db_session.add_all([c1, c2])
    db_session.flush()

    _seed_prices(db_session, c1.id, start_date, [10.0, 11.0, 12.1])
    # Ticker B starts at offset 1: price 100.0, then 110.0
    db_session.add(
        PriceBar(
            company_id=c2.id,
            date=start_date + timedelta(days=1),
            open=100.0, high=100.0, low=100.0, close=100.0, adj_close=100.0,
            provider="yfinance", interval="1d"
        )
    )
    db_session.add(
        PriceBar(
            company_id=c2.id,
            date=start_date + timedelta(days=2),
            open=110.0, high=110.0, low=110.0, close=110.0, adj_close=110.0,
            provider="yfinance", interval="1d"
        )
    )
    db_session.flush()

    index_df = calculate_equal_weight_index(db_session, symbols=["A", "B"])

    assert len(index_df) == 3
    # Day 0: only A is active, index = 100
    assert index_df.iloc[0]["index_value"] == 100.0

    # Day 1: A returns +10%. B has its first price but no return.
    # So average return is just A's return = 10%
    # Index = 110.0
    assert index_df.iloc[1]["index_value"] == pytest.approx(110.0)

    # Day 2: A returns +10% (from 11 to 12.1), B returns +10% (from 100 to 110).
    # Average return = 10%
    # Index = 110 * 1.10 = 121.0
    assert index_df.iloc[2]["index_value"] == pytest.approx(121.0)


def test_calculate_relative_performance(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    
    # Benchmarks
    c_qqq = Company(symbol="QQQ", name="QQQ", is_active=True, is_benchmark=True)
    c_nvda = Company(symbol="NVDA", name="NVDA", is_active=True, is_benchmark=True)
    db_session.add_all([c_qqq, c_nvda])
    db_session.flush()

    _seed_prices(db_session, c_qqq.id, start_date, [200.0, 210.0, 190.0])
    _seed_prices(db_session, c_nvda.id, start_date, [100.0, 120.0, 120.0])
    db_session.flush()

    # Pre-calculated index levels
    index_df = pd.DataFrame([
        {"date": start_date, "index_value": 100.0},
        {"date": start_date + timedelta(days=1), "index_value": 105.0},
        {"date": start_date + timedelta(days=2), "index_value": 110.25},
    ])

    rel_perf = calculate_relative_performance(db_session, index_df, start_date)

    assert len(rel_perf) == 3
    # Index returns: 0%, 5%, 10.25%
    assert rel_perf.iloc[0]["index_ret"] == pytest.approx(0.0)
    assert rel_perf.iloc[1]["index_ret"] == pytest.approx(5.0)
    assert rel_perf.iloc[2]["index_ret"] == pytest.approx(10.25)

    # QQQ returns: 0%, 5%, -5%
    assert rel_perf.iloc[0]["qqq_ret"] == pytest.approx(0.0)
    assert rel_perf.iloc[1]["qqq_ret"] == pytest.approx(5.0)
    assert rel_perf.iloc[2]["qqq_ret"] == pytest.approx(-5.0)

    # NVDA returns: 0%, 20%, 20%
    assert rel_perf.iloc[0]["nvda_ret"] == pytest.approx(0.0)
    assert rel_perf.iloc[1]["nvda_ret"] == pytest.approx(20.0)
    assert rel_perf.iloc[2]["nvda_ret"] == pytest.approx(20.0)


def test_calculate_top_contributors(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    c1 = Company(symbol="A", name="A", is_active=True)
    c2 = Company(symbol="B", name="B", is_active=True)
    db_session.add_all([c1, c2])
    db_session.flush()

    _seed_prices(db_session, c1.id, start_date, [10.0, 11.0])
    _seed_prices(db_session, c2.id, start_date, [20.0, 18.0])
    db_session.flush()

    contribs = calculate_top_contributors(
        db_session,
        symbols=["A", "B"],
        start_date=start_date,
        end_date=start_date + timedelta(days=1)
    )

    assert len(contribs) == 2
    # Symbol A return: +10%, contribution: +5%
    # Symbol B return: -10%, contribution: -5%
    row_a = contribs[contribs["symbol"] == "A"].iloc[0]
    row_b = contribs[contribs["symbol"] == "B"].iloc[0]

    assert row_a["return"] == pytest.approx(0.10)
    assert row_a["contribution"] == pytest.approx(0.05)
    assert row_b["return"] == pytest.approx(-0.10)
    assert row_b["contribution"] == pytest.approx(-0.05)

    # Sorted by contribution desc, so A must be first
    assert contribs.iloc[0]["symbol"] == "A"
    assert contribs.iloc[1]["symbol"] == "B"


def test_calculate_equal_weight_index_no_lookahead_bias(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    c1 = Company(symbol="A", name="A", is_active=True)
    c2 = Company(symbol="B", name="B", is_active=True)
    db_session.add_all([c1, c2])
    db_session.flush()

    # Day 0, Day 1 prices
    _seed_prices(db_session, c1.id, start_date, [10.0, 11.0])
    _seed_prices(db_session, c2.id, start_date, [20.0, 22.0])
    db_session.flush()

    index_df_past = calculate_equal_weight_index(db_session, symbols=["A", "B"])
    assert len(index_df_past) == 2
    past_val_day_1 = index_df_past.iloc[1]["index_value"]

    # Now add future prices on Day 2 with massive price shock
    _seed_prices(db_session, c1.id, start_date + timedelta(days=2), [1000.0])
    _seed_prices(db_session, c2.id, start_date + timedelta(days=2), [2000.0])
    db_session.flush()

    index_df_future = calculate_equal_weight_index(db_session, symbols=["A", "B"])
    assert len(index_df_future) == 3
    # Check that day 1 index value is EXACTLY the same as before the future price was added
    assert index_df_future.iloc[1]["index_value"] == pytest.approx(past_val_day_1)


def test_calculate_equal_weight_index_all_nan_prices(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    c1 = Company(symbol="A", name="A", is_active=True)
    db_session.add(c1)
    db_session.flush()

    # Add pricing but with None (NaN) close prices
    db_session.add(
        PriceBar(
            company_id=c1.id,
            date=start_date,
            open=None, high=None, low=None, close=None, adj_close=None,
            provider="yfinance", interval="1d"
        )
    )
    db_session.add(
        PriceBar(
            company_id=c1.id,
            date=start_date + timedelta(days=1),
            open=None, high=None, low=None, close=None, adj_close=None,
            provider="yfinance", interval="1d"
        )
    )
    db_session.flush()

    index_df = calculate_equal_weight_index(db_session, symbols=["A"])
    assert len(index_df) == 2
    # Index should remain flat at 100 because returns are NaN and filled with 0.0
    assert index_df.iloc[0]["index_value"] == 100.0
    assert index_df.iloc[1]["index_value"] == 100.0


def test_calculate_equal_weight_index_zero_price_handling(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    c1 = Company(symbol="A", name="A", is_active=True)
    db_session.add(c1)
    db_session.flush()

    # Ticker goes to 0 (or starts at 0)
    _seed_prices(db_session, c1.id, start_date, [0.0, 10.0])
    db_session.flush()

    # Verify calculate_equal_weight_index does not throw divide-by-zero
    index_df = calculate_equal_weight_index(db_session, symbols=["A"])
    assert len(index_df) == 2

    # Check top contributor with a base price of 0.0
    contribs = calculate_top_contributors(
        db_session,
        symbols=["A"],
        start_date=start_date,
        end_date=start_date + timedelta(days=1)
    )
    assert contribs.empty
    assert contribs.columns.tolist() == ["symbol", "name", "return", "contribution"]


def test_calculate_top_contributors_excludes_invalid_prices(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    valid = Company(symbol="A", name="A", is_active=True)
    invalid = Company(symbol="B", name="B", is_active=True)
    db_session.add_all([valid, invalid])
    db_session.flush()

    _seed_prices(db_session, valid.id, start_date, [10.0, 11.0])
    db_session.add(
        PriceBar(
            company_id=invalid.id,
            date=start_date,
            adj_close=None,
            provider="yfinance",
            interval="1d",
        )
    )
    db_session.add(
        PriceBar(
            company_id=invalid.id,
            date=start_date + timedelta(days=1),
            adj_close=20.0,
            provider="yfinance",
            interval="1d",
        )
    )
    db_session.flush()

    contribs = calculate_top_contributors(
        db_session,
        symbols=["A", "B"],
        start_date=start_date,
        end_date=start_date + timedelta(days=1),
    )

    assert contribs["symbol"].tolist() == ["A"]
    assert contribs.iloc[0]["return"] == pytest.approx(0.10)


def test_calculate_equal_weight_index_weight_normalization_gaps(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    c1 = Company(symbol="A", name="A", is_active=True)
    c2 = Company(symbol="B", name="B", is_active=True)
    c3 = Company(symbol="C", name="C", is_active=True)
    db_session.add_all([c1, c2, c3])
    db_session.flush()

    # Day 0: A=10, B=20, C=30
    # Day 1: A=11 (+10%), B=22 (+10%), C=NaN
    # Day 2: A=11 (0%), B=22 (0%), C=33 (+10% from 30)
    # Day 3: A=11 (0%), B=22 (0%), C=36.3 (+10% from 33)
    
    # Seed A
    _seed_prices(db_session, c1.id, start_date, [10.0, 11.0, 11.0, 11.0])
    # Seed B
    _seed_prices(db_session, c2.id, start_date, [20.0, 22.0, 22.0, 22.0])
    # Seed C with gap on day 1
    db_session.add(PriceBar(company_id=c3.id, date=start_date, adj_close=30.0, provider="yfinance", interval="1d"))
    db_session.add(PriceBar(company_id=c3.id, date=start_date + timedelta(days=2), adj_close=33.0, provider="yfinance", interval="1d"))
    db_session.add(PriceBar(company_id=c3.id, date=start_date + timedelta(days=3), adj_close=36.3, provider="yfinance", interval="1d"))
    db_session.flush()

    index_df = calculate_equal_weight_index(db_session, symbols=["A", "B", "C"])
    assert len(index_df) == 4

    # Day 0: Index = 100.0
    assert index_df.iloc[0]["index_value"] == 100.0

    # Day 1: A returns +10%, B returns +10%, C is NaN (no price on Day 1).
    # Active returns: A, B. Weight is 1/2 each.
    # Average return = 10%. Index = 100 * 1.10 = 110.0
    assert index_df.iloc[1]["index_value"] == pytest.approx(110.0)

    # Day 2: A returns 0%, B returns 0%.
    # C has price 33. But Day 1 price was missing, so C return on Day 2 is NaN.
    # Active returns: A, B. Weight is 1/2 each.
    # Average return = 0%. Index = 110.0
    assert index_df.iloc[2]["index_value"] == pytest.approx(110.0)

    # Day 3: A returns 0%, B returns 0%.
    # C returns +10% (from 33 to 36.3).
    # Active returns: A, B, C. Weight is 1/3 each.
    # Average return = 10% / 3 = 3.333%
    # Index = 110 * (1 + 0.10/3) = 113.6667
    assert index_df.iloc[3]["index_value"] == pytest.approx(110.0 * (1.0 + 0.10 / 3.0))


def test_exposure_weight_index_uses_theme_scores(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    company_a = Company(symbol="A", name="A", is_active=True)
    company_b = Company(symbol="B", name="B", is_active=True)
    theme = Theme(code="power", name="Power")
    db_session.add_all([company_a, company_b, theme])
    db_session.flush()
    db_session.add_all(
        [
            CompanyThemeExposure(
                company_id=company_a.id,
                theme_id=theme.id,
                exposure_score=3.0,
            ),
            CompanyThemeExposure(
                company_id=company_b.id,
                theme_id=theme.id,
                exposure_score=1.0,
            ),
        ]
    )
    _seed_prices(db_session, company_a.id, start_date, [100.0, 110.0])
    _seed_prices(db_session, company_b.id, start_date, [100.0, 120.0])
    create_index_definition(
        db_session,
        name="Exposure Test",
        mode=INDEX_MODE_EXPOSURE,
        company_weights={"A": 1.0, "B": 1.0},
    )
    db_session.flush()
    definition = db_session.query(IndexDefinition).filter_by(name="Exposure Test").one()

    weights = get_index_weights(db_session, definition.id)
    index_df = calculate_weighted_index(
        db_session,
        definition_id=definition.id,
        use_precomputed=False,
    )

    assert weights == pytest.approx({"A": 0.75, "B": 0.25})
    assert index_df.iloc[1]["index_value"] == pytest.approx(112.5)


def test_manual_weight_validation_and_index(db_session: Session) -> None:
    start_date = date(2026, 5, 1)
    company_a = Company(symbol="A", name="A", is_active=True)
    company_b = Company(symbol="B", name="B", is_active=True)
    db_session.add_all([company_a, company_b])
    db_session.flush()
    _seed_prices(db_session, company_a.id, start_date, [100.0, 110.0])
    _seed_prices(db_session, company_b.id, start_date, [100.0, 120.0])

    with pytest.raises(ValueError, match="100%"):
        validate_manual_weights({"A": 0.6, "B": 0.3})
    with pytest.raises(ValueError, match="non-negative"):
        validate_manual_weights({"A": 1.1, "B": -0.1})

    definition = create_index_definition(
        db_session,
        name="Manual Test",
        mode=INDEX_MODE_MANUAL,
        company_weights={"A": 0.6, "B": 0.4},
    )
    index_df = calculate_weighted_index(
        db_session,
        definition_id=definition.id,
        use_precomputed=False,
    )

    assert get_index_weights(db_session, definition.id) == pytest.approx({"A": 0.6, "B": 0.4})
    assert index_df.iloc[1]["index_value"] == pytest.approx(114.0)


def test_theme_concentration_allocates_weight_by_exposure(db_session: Session) -> None:
    company = Company(symbol="A", name="A", is_active=True)
    power = Theme(code="power", name="Power")
    cooling = Theme(code="cooling", name="Cooling")
    db_session.add_all([company, power, cooling])
    db_session.flush()
    db_session.add_all(
        [
            CompanyThemeExposure(company_id=company.id, theme_id=power.id, exposure_score=3.0),
            CompanyThemeExposure(company_id=company.id, theme_id=cooling.id, exposure_score=1.0),
        ]
    )
    definition = create_index_definition(
        db_session,
        name="Theme Test",
        mode=INDEX_MODE_MANUAL,
        company_weights={"A": 1.0},
    )

    concentration = calculate_theme_concentration(db_session, definition.id)
    by_theme = dict(zip(concentration["theme"], concentration["weight"], strict=False))

    assert by_theme["Power"] == pytest.approx(0.75)
    assert by_theme["Cooling"] == pytest.approx(0.25)


def test_ensure_default_index_definition_commits_when_dirty(db_session: Session) -> None:
    from argus.analytics.index_builder import ensure_default_index_definition, DEFAULT_INDEX_NAME
    from argus.core.models import IndexDefinition, IndexConstituent

    # Clean out any pre-existing default index definitions/constituents
    db_session.query(IndexConstituent).delete()
    db_session.query(IndexDefinition).filter_by(name=DEFAULT_INDEX_NAME).delete()
    db_session.commit()

    # Call it to trigger creation/commit
    ensure_default_index_definition(db_session)

    # Check it persisted
    assert db_session.query(IndexDefinition).filter_by(name=DEFAULT_INDEX_NAME).count() == 1
