from argus.core.models import Company, CompanyThemeExposure, Theme, Watchlist, WatchlistItem

SECTOR_GROUPS: dict[str, list[str]] = {
    "AI Capex Benchmarks": ["NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"],
    "Power and Grid": ["ETN", "GEV", "PWR", "ABBNY", "SBGSY", "SIEGY", "HUBB"],
    "Cooling and Data Center Infrastructure": ["VRT", "TT", "CARR", "JCI"],
    "Optical, Fiber, and Networking": ["CIEN", "GLW", "COHR", "LITE", "NOK", "CSCO", "ANET"],
    "Semiconductor Equipment and Advanced Packaging": ["AMAT", "KLAC", "LRCX", "ASML", "ONTO", "TER"],
    "Energy, Nuclear, and Utilities": ["CEG", "VST", "NEE", "CCJ", "SMR"],
    "Data Center REITs": ["EQIX", "DLR"],
    "Cybersecurity": ["CRWD", "PANW", "FTNT", "NET", "S", "ZS"],
    "Quantum Computing": ["IONQ", "RGTI", "QBTS", "QUBT", "INFQ", "IBM"],
    "Optional Aggressive AI Infrastructure Names": ["ALAB", "CRDO"],
}

OPTIONAL_AGGRESSIVE_SYMBOLS = set(SECTOR_GROUPS["Optional Aggressive AI Infrastructure Names"])
QUANTUM_COMPUTING_SYMBOLS = set(SECTOR_GROUPS["Quantum Computing"])
EMERGING_COMPUTE_SYMBOLS = QUANTUM_COMPUTING_SYMBOLS

THEMES: list[tuple[str, str]] = [
    ("ai_infrastructure", "AI Infrastructure"),
    ("ai_capex_benchmark", "AI Capex Benchmark"),
    ("power_grid", "Power and Grid"),
    ("cooling", "Cooling and Data Center Infrastructure"),
    ("optical_networking", "Optical, Fiber, and Networking"),
    ("semiconductor_equipment", "Semiconductor Equipment"),
    ("energy_nuclear_utilities", "Energy, Nuclear, and Utilities"),
    ("data_center_reit", "Data Center REIT"),
    ("cybersecurity", "Cybersecurity"),
    ("aggressive_ai_infra", "Aggressive AI Infrastructure"),
    ("hyperscaler_capex", "Hyperscaler Capex"),
    ("emerging_compute", "Emerging Compute"),
    ("quantum_computing", "Quantum Computing"),
    ("neuromorphic_computing", "Neuromorphic Computing"),
    ("advanced_packaging", "Advanced Packaging"),
]

THEME_PARENT_CODES: dict[str, str | None] = {
    "ai_infrastructure": None,
    "ai_capex_benchmark": "ai_infrastructure",
    "power_grid": "ai_infrastructure",
    "cooling": "ai_infrastructure",
    "optical_networking": "ai_infrastructure",
    "semiconductor_equipment": "ai_infrastructure",
    "energy_nuclear_utilities": "ai_infrastructure",
    "data_center_reit": "ai_infrastructure",
    "cybersecurity": "ai_infrastructure",
    "aggressive_ai_infra": "ai_infrastructure",
    "hyperscaler_capex": "ai_infrastructure",
    "emerging_compute": None,
    "quantum_computing": "emerging_compute",
    "neuromorphic_computing": "emerging_compute",
    "advanced_packaging": "ai_infrastructure",
}

BENCHMARKS = {"NVDA", "MSFT", "AMZN", "GOOGL", "META", "QQQ"}
HYPERSCALERS = {"MSFT", "AMZN", "GOOGL", "META"}
AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS = (
    BENCHMARKS | OPTIONAL_AGGRESSIVE_SYMBOLS | EMERGING_COMPUTE_SYMBOLS
)
AI_INFRA_CORE_INDEX_SYMBOLS = {
    symbol
    for symbols in SECTOR_GROUPS.values()
    for symbol in symbols
    if symbol not in AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS
}
WATCH_STATUSES = {"ignore", "watch", "high_priority", "owned"}
WATCH_STATUS_BY_SYMBOL = {
    "NVDA": "high_priority",
    "MSFT": "high_priority",
    "AMZN": "owned",
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
    "Cybersecurity": ["cybersecurity"],
    "Quantum Computing": ["quantum_computing"],
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
    "CRWD": "CrowdStrike Holdings, Inc.",
    "PANW": "Palo Alto Networks, Inc.",
    "FTNT": "Fortinet, Inc.",
    "NET": "Cloudflare, Inc.",
    "S": "SentinelOne, Inc.",
    "ZS": "Zscaler, Inc.",
    "IONQ": "IonQ, Inc.",
    "RGTI": "Rigetti Computing, Inc.",
    "QBTS": "D-Wave Quantum Inc.",
    "QUBT": "Quantum Computing Inc.",
    "INFQ": "Infleqtion, Inc.",
    "IBM": "International Business Machines Corporation",
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
    "CRWD": {"exchange": "NASDAQ", "country": "US", "industry": "Cybersecurity"},
    "PANW": {"exchange": "NASDAQ", "country": "US", "industry": "Cybersecurity"},
    "FTNT": {"exchange": "NASDAQ", "country": "US", "industry": "Cybersecurity"},
    "NET": {"exchange": "NYSE", "country": "US", "industry": "Cybersecurity"},
    "S": {"exchange": "NYSE", "country": "US", "industry": "Cybersecurity"},
    "ZS": {"exchange": "NASDAQ", "country": "US", "industry": "Cybersecurity"},
    "IONQ": {"exchange": "NYSE", "country": "US", "industry": "Quantum Computing"},
    "RGTI": {"exchange": "NASDAQ", "country": "US", "industry": "Quantum Computing"},
    "QBTS": {"exchange": "NYSE", "country": "US", "industry": "Quantum Computing"},
    "QUBT": {"exchange": "NASDAQ", "country": "US", "industry": "Quantum Computing"},
    "INFQ": {"exchange": "NYSE", "country": "US", "industry": "Quantum Computing"},
    "IBM": {"exchange": "NYSE", "country": "US", "industry": "Quantum Computing"},
    "ALAB": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductors"},
    "CRDO": {"exchange": "NASDAQ", "country": "US", "industry": "Semiconductors"},
}


COMPANY_CIKS = {
    "NVDA": "0001045810",
    "MSFT": "0000789019",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "QQQ": "0001067839",
    "ETN": "0001551182",
    "GEV": "0001996810",
    "PWR": "0001050915",
    "ABBNY": "0001091587",
    "SBGSY": "0001438902",
    "SIEGY": "0001012920",
    "HUBB": "0000048898",
    "VRT": "0001674101",
    "TT": "0001466258",
    "CARR": "0001783180",
    "JCI": "0000833444",
    "CIEN": "0000936395",
    "GLW": "0000024741",
    "COHR": "0000820318",
    "LITE": "0001633978",
    "NOK": "0000924613",
    "CSCO": "0000858877",
    "ANET": "0001596532",
    "AMAT": "0000006951",
    "KLAC": "0000319201",
    "LRCX": "0000707549",
    "ASML": "0000937966",
    "ONTO": "0000704532",
    "TER": "0000097210",
    "CEG": "0001868275",
    "VST": "0001692819",
    "NEE": "0000753308",
    "CCJ": "0001009001",
    "SMR": "0001822966",
    "EQIX": "0001101239",
    "DLR": "0001297996",
    "CRWD": "0001535527",
    "PANW": "0001327567",
    "FTNT": "0001262039",
    "NET": "0001477333",
    "S": "0001583708",
    "ZS": "0001713683",
    "IONQ": "0001824920",
    "RGTI": "0001838359",
    "QBTS": "0001907982",
    "QUBT": "0001758009",
    "INFQ": "0002007825",
    "IBM": "0000051143",
    "ALAB": "0001736297",
    "CRDO": "0001807794",
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
    session.flush()

    themes_by_code = {theme.code: theme for theme in session.query(Theme).all()}
    for code, name in THEMES:
        theme = themes_by_code[code]
        theme.name = name
        theme.description = theme.description or name
        parent_code = THEME_PARENT_CODES.get(code)
        theme.parent_theme_id = themes_by_code[parent_code].id if parent_code else None


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
                company.cik = company.cik or COMPANY_CIKS.get(symbol)
                continue
            session.add(
                Company(
                    symbol=symbol,
                    name=COMPANY_NAMES.get(symbol, symbol),
                    exchange=metadata["exchange"],
                    sector=sector,
                    industry=metadata["industry"],
                    country=metadata["country"],
                    cik=COMPANY_CIKS.get(symbol),
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

        expected_theme_ids = {
            theme_map[code]
            for code in theme_codes
            if code in theme_map
        }
        _remove_obsolete_seed_exposures(session, company, expected_theme_ids)

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

            score = _default_exposure_score(code)
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


def _remove_obsolete_seed_exposures(session, company: Company, expected_theme_ids: set[int]) -> None:
    stale_seed_exposures = (
        session.query(CompanyThemeExposure)
        .filter(
            CompanyThemeExposure.company_id == company.id,
            CompanyThemeExposure.source == "manual_seed",
            CompanyThemeExposure.theme_id.notin_(expected_theme_ids),
        )
        .all()
    )
    for exposure in stale_seed_exposures:
        session.delete(exposure)


def _default_exposure_score(theme_code: str) -> float:
    if theme_code in {"ai_capex_benchmark", "quantum_computing"}:
        return 5.0
    return 4.0
