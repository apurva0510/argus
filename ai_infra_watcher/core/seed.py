from ai_infra_watcher.core.models import Company, CompanyThemeExposure, Theme, Watchlist, WatchlistItem

SECTOR_GROUPS: dict[str, list[str]] = {
    "AI Capex Benchmarks": ["NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"],
    "Power and Grid": ["ETN", "GEV", "PWR", "ABBNY", "SBGSY", "SIEGY", "HUBB"],
    "Cooling and Data Center Infrastructure": ["VRT", "TT", "CARR", "JCI"],
    "Optical, Fiber, and Networking": ["CIEN", "GLW", "COHR", "LITE", "NOK", "CSCO", "ANET"],
    "Semicap and Advanced Packaging": ["AMAT", "KLAC", "LRCX", "ASML", "ONTO", "TER"],
    "Energy, Nuclear, and Utilities": ["CEG", "VST", "NEE", "CCJ", "SMR"],
    "Data Center REITs": ["EQIX", "DLR"],
    "Optional Aggressive": ["ALAB", "CRDO"],
}

THEMES = [
    ("power_grid", "Power Grid"),
    ("cooling", "Cooling"),
    ("optical_networking", "Optical Networking"),
    ("semicap", "Semicap"),
    ("advanced_packaging", "Advanced Packaging"),
    ("nuclear_power", "Nuclear Power"),
    ("data_center_reit", "Data Center REIT"),
    ("construction", "Construction"),
    ("hyperscaler_capex", "Hyperscaler Capex"),
    ("benchmark", "Benchmark"),
]

BENCHMARKS = {"NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"}
HYPERSCALERS = {"MSFT", "AMZN", "GOOGL", "META"}
COMPANY_NAMES = {
    "NVDA": "NVIDIA Corporation",
    "MSFT": "Microsoft Corporation",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",
    "QQQ": "Invesco QQQ Trust",
    "ETN": "Eaton Corporation plc",
    "GEV": "GE Vernova Inc.",
    "PWR": "Quanta Services, Inc.",
    "ABBNY": "ABB Ltd",
    "SBGSY": "Schneider Electric SE",
    "SIEGY": "Siemens AG",
    "HUBB": "Hubbell Incorporated",
    "VRT": "Vertiv Holdings Co",
    "TT": "Trane Technologies plc",
    "CARR": "Carrier Global Corporation",
    "JCI": "Johnson Controls International plc",
    "CIEN": "Ciena Corporation",
    "GLW": "Corning Incorporated",
    "COHR": "Coherent Corp.",
    "LITE": "Lumentum Holdings Inc.",
    "NOK": "Nokia Corporation",
    "CSCO": "Cisco Systems, Inc.",
    "ANET": "Arista Networks, Inc.",
    "AMAT": "Applied Materials, Inc.",
    "KLAC": "KLA Corporation",
    "LRCX": "Lam Research Corporation",
    "ASML": "ASML Holding N.V.",
    "ONTO": "Onto Innovation Inc.",
    "TER": "Teradyne, Inc.",
    "CEG": "Constellation Energy Corporation",
    "VST": "Vistra Corp.",
    "NEE": "NextEra Energy, Inc.",
    "CCJ": "Cameco Corporation",
    "SMR": "NuScale Power Corporation",
    "EQIX": "Equinix, Inc.",
    "DLR": "Digital Realty Trust, Inc.",
    "ALAB": "Astera Labs, Inc.",
    "CRDO": "Credo Technology Group Holding Ltd",
}


def seed_themes(session) -> None:
    existing = {t.code for t in session.query(Theme).all()}
    for code, name in THEMES:
        if code not in existing:
            session.add(Theme(code=code, name=name, description=name))


def seed_companies(session) -> None:
    for sector, symbols in SECTOR_GROUPS.items():
        for symbol in symbols:
            company = session.query(Company).filter(Company.symbol == symbol).one_or_none()
            if company:
                company.name = COMPANY_NAMES.get(symbol, company.name)
                company.sector = sector
                continue
            session.add(
                Company(
                    symbol=symbol,
                    name=COMPANY_NAMES.get(symbol, symbol),
                    exchange="",
                    sector=sector,
                    industry="",
                    country="US",
                    cik=None,
                    is_active=True,
                    is_benchmark=symbol in BENCHMARKS,
                    is_hyperscaler=symbol in HYPERSCALERS,
                )
            )


def seed_watchlists(session) -> None:
    for sector in SECTOR_GROUPS:
        watchlist = session.query(Watchlist).filter(Watchlist.name == sector).one_or_none()
        if watchlist is None:
            watchlist = Watchlist(name=sector, description=f"System watchlist: {sector}", is_system=True)
            session.add(watchlist)
            session.flush()

        companies = session.query(Company).filter(Company.sector == sector).all()
        for idx, company in enumerate(companies, start=1):
            existing_item = (
                session.query(WatchlistItem)
                .filter(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.company_id == company.id)
                .one_or_none()
            )
            if existing_item is None:
                session.add(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        company_id=company.id,
                        watch_status="watch",
                        sort_order=idx,
                        notes="",
                    )
                )


def seed_exposure_defaults(session) -> None:
    theme_map = {theme.code: theme.id for theme in session.query(Theme).all()}
    for company in session.query(Company).all():
        if company.is_benchmark:
            code = "benchmark"
            score = 5.0
        elif "Power" in (company.sector or "") or "Energy" in (company.sector or ""):
            code = "power_grid"
            score = 4.0
        elif "Cooling" in (company.sector or ""):
            code = "cooling"
            score = 4.0
        elif "Optical" in (company.sector or ""):
            code = "optical_networking"
            score = 4.0
        elif "Semicap" in (company.sector or ""):
            code = "semicap"
            score = 4.0
        elif "REIT" in (company.sector or ""):
            code = "data_center_reit"
            score = 4.0
        else:
            code = "construction"
            score = 3.0

        theme_id = theme_map.get(code)
        if not theme_id:
            continue

        exists = (
            session.query(CompanyThemeExposure)
            .filter(
                CompanyThemeExposure.company_id == company.id,
                CompanyThemeExposure.theme_id == theme_id,
            )
            .one_or_none()
        )
        if exists is None:
            session.add(
                CompanyThemeExposure(
                    company_id=company.id,
                    theme_id=theme_id,
                    exposure_score=score,
                    confidence="seed",
                    source="manual_seed",
                    notes="Initial default exposure",
                    as_of_date=None,
                )
            )
