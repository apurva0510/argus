from argus.core.models import Company, CompanyThemeExposure, Theme, Watchlist, WatchlistItem

SECTOR_GROUPS: dict[str, list[str]] = {
    "AI Capex Benchmarks": ["NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"],
    "Power and Grid": ["ETN", "GEV", "PWR", "ABBNY", "SBGSY", "SIEGY", "HUBB"],
    "Cooling and Data Center Infrastructure": ["VRT", "TT", "CARR", "JCI"],
    "Optical, Fiber, and Networking": ["CIEN", "GLW", "COHR", "LITE", "NOK", "CSCO", "ANET"],
    "Semiconductor Equipment and Advanced Packaging": ["AMAT", "KLAC", "LRCX", "ASML", "ONTO", "TER"],
    "Energy, Nuclear, and Utilities": ["CEG", "VST", "NEE", "CCJ", "SMR"],
    "Data Center REITs": ["EQIX", "DLR"],
    "Optional Aggressive AI Infrastructure Names": ["ALAB", "CRDO"],
}

OPTIONAL_AGGRESSIVE_SYMBOLS = set(SECTOR_GROUPS["Optional Aggressive AI Infrastructure Names"])

THEMES: list[tuple[str, str]] = [
    ("ai_capex_benchmark", "AI Capex Benchmark"),
    ("power_grid", "Power and Grid"),
    ("cooling", "Cooling and Data Center Infrastructure"),
    ("optical_networking", "Optical, Fiber, and Networking"),
    ("semiconductor_equipment", "Semiconductor Equipment"),
    ("advanced_packaging", "Advanced Packaging"),
    ("energy_nuclear_utilities", "Energy, Nuclear, and Utilities"),
    ("data_center_reit", "Data Center REIT"),
    ("aggressive_ai_infra", "Aggressive AI Infrastructure"),
    ("hyperscaler_capex", "Hyperscaler Capex"),
]

BENCHMARKS = {"NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"}
HYPERSCALERS = {"MSFT", "AMZN", "GOOGL", "META"}
AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS = BENCHMARKS | OPTIONAL_AGGRESSIVE_SYMBOLS
AI_INFRA_CORE_INDEX_SYMBOLS = {
    symbol
    for symbols in SECTOR_GROUPS.values()
    for symbol in symbols
    if symbol not in AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS
}
WATCH_STATUSES = {"ignore", "watch", "high_priority", "owned"}
WATCH_STATUS_BY_SYMBOL = {
    "NVDA": "high_priority",
    "MSFT": "owned",
    "AMZN": "high_priority",
    "GOOGL": "watch",
    "META": "watch",
    "QQQ": "watch",
    "ALAB": "ignore",
    "CRDO": "ignore",
}

SECTOR_THEME_CODES: dict[str, list[str]] = {
    "AI Capex Benchmarks": ["ai_capex_benchmark"],
    "Power and Grid": ["power_grid"],
    "Cooling and Data Center Infrastructure": ["cooling"],
    "Optical, Fiber, and Networking": ["optical_networking"],
    "Semiconductor Equipment and Advanced Packaging": ["semiconductor_equipment", "advanced_packaging"],
    "Energy, Nuclear, and Utilities": ["energy_nuclear_utilities"],
    "Data Center REITs": ["data_center_reit"],
    "Optional Aggressive AI Infrastructure Names": ["aggressive_ai_infra"],
}
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

COMPANY_METADATA = {
    "NVDA": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductors"},
    "MSFT": {"exchange": "NASDAQ", "country": "US", "industry": "Software"},
    "AMZN": {"exchange": "NASDAQ", "country": "US", "industry": "Internet Retail"},
    "GOOGL": {"exchange": "NASDAQ", "country": "US", "industry": "Internet Services"},
    "META": {"exchange": "NASDAQ", "country": "US", "industry": "Internet Services"},
    "QQQ": {"exchange": "NASDAQ", "country": "US", "industry": "ETF"},
    "ETN": {"exchange": "NYSE", "country": "Ireland", "industry": "Electrical Equipment"},
    "GEV": {"exchange": "NYSE", "country": "US", "industry": "Power Equipment"},
    "PWR": {"exchange": "NYSE", "country": "US", "industry": "Engineering and Construction"},
    "ABBNY": {"exchange": "OTC", "country": "Switzerland", "industry": "ADR"},
    "SBGSY": {"exchange": "OTC", "country": "France", "industry": "ADR"},
    "SIEGY": {"exchange": "OTC", "country": "Germany", "industry": "ADR"},
    "HUBB": {"exchange": "NYSE", "country": "US", "industry": "Electrical Equipment"},
    "VRT": {"exchange": "NYSE", "country": "US", "industry": "Data Center Infrastructure"},
    "TT": {"exchange": "NYSE", "country": "Ireland", "industry": "HVAC"},
    "CARR": {"exchange": "NYSE", "country": "US", "industry": "HVAC"},
    "JCI": {"exchange": "NYSE", "country": "Ireland", "industry": "Building Systems"},
    "CIEN": {"exchange": "NYSE", "country": "US", "industry": "Optical Networking"},
    "GLW": {"exchange": "NYSE", "country": "US", "industry": "Optical Fiber"},
    "COHR": {"exchange": "NYSE", "country": "US", "industry": "Optical Components"},
    "LITE": {"exchange": "NASDAQ", "country": "US", "industry": "Optical Components"},
    "NOK": {"exchange": "NYSE", "country": "Finland", "industry": "ADR"},
    "CSCO": {"exchange": "NASDAQ", "country": "US", "industry": "Networking"},
    "ANET": {"exchange": "NYSE", "country": "US", "industry": "Networking"},
    "AMAT": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductor Equipment"},
    "KLAC": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductor Equipment"},
    "LRCX": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductor Equipment"},
    "ASML": {"exchange": "NASDAQ", "country": "Netherlands", "industry": "ADR"},
    "ONTO": {"exchange": "NYSE", "country": "US", "industry": "Semiconductor Equipment"},
    "TER": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductor Equipment"},
    "CEG": {"exchange": "NASDAQ", "country": "US", "industry": "Electric Utility"},
    "VST": {"exchange": "NYSE", "country": "US", "industry": "Electric Utility"},
    "NEE": {"exchange": "NYSE", "country": "US", "industry": "Electric Utility"},
    "CCJ": {"exchange": "NYSE", "country": "Canada", "industry": "Uranium"},
    "SMR": {"exchange": "NYSE", "country": "US", "industry": "Nuclear Power"},
    "EQIX": {"exchange": "NASDAQ", "country": "US", "industry": "Data Center REIT"},
    "DLR": {"exchange": "NYSE", "country": "US", "industry": "Data Center REIT"},
    "ALAB": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductors"},
    "CRDO": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductors"},
}


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _company_metadata(symbol: str) -> dict[str, str]:
    return COMPANY_METADATA.get(symbol, {"exchange": "UNKNOWN", "country": "UNKNOWN", "industry": "UNKNOWN"})


def seed_themes(session) -> None:
    existing = {t.code for t in session.query(Theme).all()}
    for code, name in THEMES:
        if code not in existing:
            session.add(Theme(code=code, name=name, description=name))


def seed_companies(session) -> None:
    seen_symbols: set[str] = set()
    for sector, symbols in SECTOR_GROUPS.items():
        for raw_symbol in symbols:
            symbol = normalize_symbol(raw_symbol)
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            metadata = _company_metadata(symbol)
            company = session.query(Company).filter(Company.symbol == symbol).one_or_none()
            if company:
                company.name = COMPANY_NAMES.get(symbol, company.name)
                company.exchange = metadata["exchange"]
                company.sector = sector
                company.industry = metadata["industry"]
                company.country = metadata["country"]
                company.is_benchmark = symbol in BENCHMARKS
                company.is_hyperscaler = symbol in HYPERSCALERS
                continue
            session.add(
                Company(
                    symbol=symbol,
                    name=COMPANY_NAMES.get(symbol, symbol),
                    exchange=metadata["exchange"],
                    sector=sector,
                    industry=metadata["industry"],
                    country=metadata["country"],
                    cik=None,
                    is_active=True,
                    is_benchmark=symbol in BENCHMARKS,
                    is_hyperscaler=symbol in HYPERSCALERS,
                )
            )


def seed_watchlists(session) -> None:
    for sector, symbols in SECTOR_GROUPS.items():
        watchlist = session.query(Watchlist).filter(Watchlist.name == sector).one_or_none()
        if watchlist is None:
            watchlist = Watchlist(name=sector, description=f"System watchlist: {sector}", is_system=True)
            session.add(watchlist)
            session.flush()

        for idx, raw_symbol in enumerate(symbols, start=1):
            symbol = normalize_symbol(raw_symbol)
            company = session.query(Company).filter(Company.symbol == symbol).one_or_none()
            if company is None:
                continue
            existing_item = (
                session.query(WatchlistItem)
                .filter(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.company_id == company.id)
                .one_or_none()
            )
            status = WATCH_STATUS_BY_SYMBOL.get(company.symbol, "watch")
            if status not in WATCH_STATUSES:
                status = "watch"
            if existing_item is None:
                session.add(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        company_id=company.id,
                        watch_status=status,
                        sort_order=idx,
                        notes="",
                    )
                )
            else:
                if existing_item.watch_status not in WATCH_STATUSES:
                    existing_item.watch_status = status
                existing_item.sort_order = idx


def seed_exposure_defaults(session) -> None:
    theme_map = {theme.code: theme.id for theme in session.query(Theme).all()}
    for company in session.query(Company).all():
        theme_codes = list(SECTOR_THEME_CODES.get(company.sector or "", []))
        if company.is_benchmark and "ai_capex_benchmark" not in theme_codes:
            theme_codes.append("ai_capex_benchmark")
        if company.is_hyperscaler and "hyperscaler_capex" not in theme_codes:
            theme_codes.append("hyperscaler_capex")

        if not theme_codes:
            continue

        for code in theme_codes:
            theme_id = theme_map.get(code)
            if theme_id is None:
                continue

            exists = (
                session.query(CompanyThemeExposure)
                .filter(
                    CompanyThemeExposure.company_id == company.id,
                    CompanyThemeExposure.theme_id == theme_id,
                )
                .one_or_none()
            )
            if exists is not None:
                continue

            score = 5.0 if code == "ai_capex_benchmark" else 4.0
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
