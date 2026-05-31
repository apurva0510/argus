import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from argus.core.db import Base, create_database_engine
from argus.core.models import Company, CompanyThemeExposure, Theme, Watchlist, WatchlistItem
from argus.core.seed import (
    AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS,
    AI_INFRA_CORE_INDEX_SYMBOLS,
    BENCHMARKS,
    COMPANY_METADATA,
    COMPANY_NAMES,
    SECTOR_GROUPS,
    SECTOR_THEME_CODES,
    THEMES,
    WATCH_STATUSES,
    WATCH_STATUS_BY_SYMBOL,
    normalize_symbol,
    seed_companies,
    seed_exposure_defaults,
    seed_themes,
    seed_watchlists,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SECTOR_GROUPS = {
    "AI Capex Benchmarks": ["NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"],
    "Power and Grid": ["ETN", "GEV", "PWR", "ABBNY", "SBGSY", "SIEGY", "HUBB"],
    "Cooling and Data Center Infrastructure": ["VRT", "TT", "CARR", "JCI"],
    "Optical, Fiber, and Networking": ["CIEN", "GLW", "COHR", "LITE", "NOK", "CSCO", "ANET"],
    "Semiconductor Equipment and Advanced Packaging": ["AMAT", "KLAC", "LRCX", "ASML", "ONTO", "TER"],
    "Energy, Nuclear, and Utilities": ["CEG", "VST", "NEE", "CCJ", "SMR"],
    "Data Center REITs": ["EQIX", "DLR"],
    "Cybersecurity": ["CRWD", "PANW", "FTNT", "NET", "S", "ZS"],
    "Optional Aggressive AI Infrastructure Names": ["ALAB", "CRDO"],
}

EXPECTED_THEME_CODES = {
    "ai_capex_benchmark",
    "power_grid",
    "cooling",
    "optical_networking",
    "semiconductor_equipment",
    "advanced_packaging",
    "energy_nuclear_utilities",
    "data_center_reit",
    "cybersecurity",
    "aggressive_ai_infra",
    "hyperscaler_capex",
}


def _expected_company_count() -> int:
    return len({normalize_symbol(ticker) for tickers in SECTOR_GROUPS.values() for ticker in tickers})


def _expected_exposure_count() -> int:
    return sum(
        len(
            set(SECTOR_THEME_CODES[sector])
            | ({"ai_capex_benchmark"} if symbol in BENCHMARKS else set())
            | ({"hyperscaler_capex"} if symbol in {"MSFT", "AMZN", "GOOGL", "META"} else set())
        )
        for sector, symbols in SECTOR_GROUPS.items()
        for symbol in symbols
    )


def _run_seed(session: Session) -> None:
    seed_themes(session)
    session.flush()
    seed_companies(session)
    session.flush()
    seed_watchlists(session)
    seed_exposure_defaults(session)
    session.commit()


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return factory()


def test_no_duplicate_tickers_in_seed_data() -> None:
    tickers = [ticker for tickers in SECTOR_GROUPS.values() for ticker in tickers]
    assert len(tickers) == len(set(tickers))
    assert all(ticker == normalize_symbol(ticker) for ticker in tickers)


def test_seed_groups_match_build_plan() -> None:
    assert SECTOR_GROUPS == EXPECTED_SECTOR_GROUPS


def test_theme_codes_match_canonical_set() -> None:
    theme_codes = {code for code, _name in THEMES}
    assert theme_codes == EXPECTED_THEME_CODES
    assert set(SECTOR_THEME_CODES) == set(SECTOR_GROUPS)
    assert {
        code for theme_codes_for_sector in SECTOR_THEME_CODES.values() for code in theme_codes_for_sector
    }.issubset(theme_codes)


def test_company_name_and_metadata_coverage() -> None:
    tickers = {ticker for tickers in SECTOR_GROUPS.values() for ticker in tickers}
    assert set(COMPANY_NAMES) == tickers
    assert set(COMPANY_METADATA) == tickers


def test_every_seeded_company_has_at_least_one_theme() -> None:
    with _session() as session:
        _run_seed(session)
        missing_count = (
            session.query(func.count(Company.id))
            .outerjoin(CompanyThemeExposure, CompanyThemeExposure.company_id == Company.id)
            .filter(CompanyThemeExposure.id.is_(None))
            .scalar()
        )
        assert missing_count == 0


def test_every_seeded_ticker_belongs_to_at_least_one_watchlist() -> None:
    with _session() as session:
        _run_seed(session)
        missing_count = (
            session.query(func.count(Company.id))
            .outerjoin(WatchlistItem, WatchlistItem.company_id == Company.id)
            .filter(WatchlistItem.id.is_(None))
            .scalar()
        )
        assert missing_count == 0


def test_benchmark_names_marked_correctly() -> None:
    with _session() as session:
        _run_seed(session)
        benchmark_symbols = {
            symbol for (symbol,) in session.query(Company.symbol).filter(Company.is_benchmark.is_(True)).all()
        }
        assert benchmark_symbols == BENCHMARKS


def test_seed_is_idempotent_when_run_multiple_times() -> None:
    with _session() as session:
        _run_seed(session)
        first_counts = {
            "companies": session.query(func.count(Company.id)).scalar(),
            "themes": session.query(func.count(Theme.id)).scalar(),
            "watchlists": session.query(func.count(Watchlist.id)).scalar(),
            "watchlist_items": session.query(func.count(WatchlistItem.id)).scalar(),
            "exposures": session.query(func.count(CompanyThemeExposure.id)).scalar(),
        }

        _run_seed(session)
        second_counts = {
            "companies": session.query(func.count(Company.id)).scalar(),
            "themes": session.query(func.count(Theme.id)).scalar(),
            "watchlists": session.query(func.count(Watchlist.id)).scalar(),
            "watchlist_items": session.query(func.count(WatchlistItem.id)).scalar(),
            "exposures": session.query(func.count(CompanyThemeExposure.id)).scalar(),
        }

        assert first_counts == second_counts
        assert second_counts == {
            "companies": _expected_company_count(),
            "themes": len(THEMES),
            "watchlists": len(SECTOR_GROUPS),
            "watchlist_items": _expected_company_count(),
            "exposures": _expected_exposure_count(),
        }


def test_seed_creates_unique_watchlist_items_and_theme_exposures() -> None:
    with _session() as session:
        _run_seed(session)

        duplicate_watchlist_items = (
            session.query(
                WatchlistItem.watchlist_id,
                WatchlistItem.company_id,
                func.count(WatchlistItem.id),
            )
            .group_by(WatchlistItem.watchlist_id, WatchlistItem.company_id)
            .having(func.count(WatchlistItem.id) > 1)
            .all()
        )
        duplicate_exposures = (
            session.query(
                CompanyThemeExposure.company_id,
                CompanyThemeExposure.theme_id,
                func.count(CompanyThemeExposure.id),
            )
            .group_by(CompanyThemeExposure.company_id, CompanyThemeExposure.theme_id)
            .having(func.count(CompanyThemeExposure.id) > 1)
            .all()
        )

        assert duplicate_watchlist_items == []
        assert duplicate_exposures == []


def test_seed_normalizes_tickers_before_insert(monkeypatch) -> None:
    monkeypatch.setitem(SECTOR_GROUPS, "AI Capex Benchmarks", [" nvda ", "NVDA"])

    with _session() as session:
        seed_companies(session)
        session.commit()

        symbols = [symbol for (symbol,) in session.query(Company.symbol).all()]
        assert symbols.count("NVDA") == 1
        assert " nvda " not in symbols


def test_system_watchlists_match_seed_groups_and_order() -> None:
    with _session() as session:
        _run_seed(session)

        watchlist_names = {name for (name,) in session.query(Watchlist.name).all()}
        assert watchlist_names == set(SECTOR_GROUPS)

        for watchlist_name, expected_symbols in SECTOR_GROUPS.items():
            rows = (
                session.query(Company.symbol, WatchlistItem.sort_order)
                .join(WatchlistItem, WatchlistItem.company_id == Company.id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .filter(Watchlist.name == watchlist_name)
                .order_by(WatchlistItem.sort_order)
                .all()
            )
            assert [symbol for symbol, _sort_order in rows] == expected_symbols
            assert [sort_order for _symbol, sort_order in rows] == list(
                range(1, len(expected_symbols) + 1)
            )


def test_company_metadata_is_seeded() -> None:
    with _session() as session:
        _run_seed(session)

        companies = session.query(Company).all()
        assert all(company.exchange for company in companies)
        assert all(company.country for company in companies)
        assert all(company.industry for company in companies)

        by_symbol = {company.symbol: company for company in companies}
        assert by_symbol["QQQ"].industry == "ETF"
        assert by_symbol["ABBNY"].exchange == "OTC"
        assert by_symbol["ABBNY"].country == "Switzerland"
        assert by_symbol["ASML"].country == "Netherlands"
        assert by_symbol["CCJ"].country == "Canada"


def test_seeded_themes_match_canonical_set() -> None:
    with _session() as session:
        _run_seed(session)
        theme_codes = {code for (code,) in session.query(Theme.code).all()}
        assert theme_codes == EXPECTED_THEME_CODES


def test_ai_infra_core_index_excludes_benchmarks_and_optional_aggressive_names() -> None:
    all_seeded_symbols = {symbol for symbols in SECTOR_GROUPS.values() for symbol in symbols}

    assert AI_INFRA_CORE_INDEX_SYMBOLS
    assert AI_INFRA_CORE_INDEX_SYMBOLS.isdisjoint(BENCHMARKS)
    assert AI_INFRA_CORE_INDEX_SYMBOLS.isdisjoint({"ALAB", "CRDO"})
    assert AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS == BENCHMARKS | {"ALAB", "CRDO"}
    assert AI_INFRA_CORE_INDEX_SYMBOLS | AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS == all_seeded_symbols


def test_watch_status_values_are_supported() -> None:
    with _session() as session:
        _run_seed(session)
        statuses = {status for (status,) in session.query(WatchlistItem.watch_status).distinct().all()}
        assert statuses.issubset(WATCH_STATUSES)
        assert WATCH_STATUSES.issuperset({"ignore", "watch", "high_priority", "owned"})
        assert set(WATCH_STATUS_BY_SYMBOL.values()).issubset(WATCH_STATUSES)
        assert set(WATCH_STATUS_BY_SYMBOL).issubset(COMPANY_NAMES)


def test_seed_script_is_idempotent_with_temporary_sqlite_database(tmp_path) -> None:
    db_path = tmp_path / "seed_script.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(bind=engine)
    engine.dispose()

    env = os.environ.copy()
    env.update(
        {
            "APP_PASSWORD": "",
            "DATABASE_URL": database_url,
            "PYTHONPATH": str(PROJECT_ROOT),
            "SEC_USER_AGENT": "",
        }
    )

    for _run_number in range(2):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "seed_companies.py")],
            cwd=tmp_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "Seed data loaded." in result.stdout

    with sqlite3.connect(db_path) as connection:
        counts = {
            table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in [
                "companies",
                "themes",
                "watchlists",
                "watchlist_items",
                "company_theme_exposure",
            ]
        }

    assert counts == {
        "companies": _expected_company_count(),
        "themes": len(THEMES),
        "watchlists": len(SECTOR_GROUPS),
        "watchlist_items": _expected_company_count(),
        "company_theme_exposure": _expected_exposure_count(),
    }
