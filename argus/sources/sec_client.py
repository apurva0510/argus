import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
import httpx

from argus.core.settings import settings

logger = logging.getLogger(__name__)

# SEC rate limit is 10 requests per second. The plan specifies no more than 8 requests per second.
# This means at least 0.13 seconds between queries.
SEC_RATE_LIMIT_DELAY = 0.15
SEC_TICKER_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
_last_request_time = 0.0


@dataclass(frozen=True)
class SecTickerIdentity:
    ticker: str
    cik: str
    name: str
    exchange: str | None = None


class SecSubmissionNotFoundError(RuntimeError):
    def __init__(self, cik: str):
        self.cik = str(cik).zfill(10)
        super().__init__(f"SEC submissions not found for CIK {self.cik}")


def rate_limit_sec() -> None:
    """Enforces rate limit delay between SEC EDGAR requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    wait_time = SEC_RATE_LIMIT_DELAY - elapsed
    if wait_time > 0:
        time.sleep(wait_time)
    _last_request_time = time.time()


def _sec_headers() -> dict[str, str]:
    user_agent = settings.sec_user_agent
    if not user_agent or not user_agent.strip():
        raise ValueError("SEC_USER_AGENT is not configured. Please set it in environment or .env file.")
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


def normalize_cik(cik: str | int) -> str:
    cik_str = str(cik).strip()
    if not cik_str.isdigit() or len(cik_str) > 10:
        raise ValueError(f"Invalid SEC CIK: {cik}")
    return cik_str.zfill(10)


def _normalized_name_tokens(name: str) -> set[str]:
    legal_suffixes = {
        "AG",
        "CO",
        "COMPANY",
        "CORP",
        "CORPORATION",
        "INC",
        "INCORPORATED",
        "LTD",
        "LIMITED",
        "LLC",
        "LP",
        "NV",
        "PLC",
        "SA",
        "SE",
    }
    return {
        token
        for token in re.findall(r"[A-Z0-9]+", name.upper())
        if token not in legal_suffixes
    }


def sec_identity_matches_company(identity: SecTickerIdentity, company_name: str) -> bool:
    """Return whether an SEC issuer name is compatible with the configured company name."""
    company_tokens = _normalized_name_tokens(company_name)
    sec_tokens = _normalized_name_tokens(identity.name)
    if not company_tokens or not sec_tokens:
        return False
    overlap = company_tokens & sec_tokens
    return bool(overlap) and (
        company_tokens.issubset(sec_tokens)
        or sec_tokens.issubset(company_tokens)
        or len(overlap) / min(len(company_tokens), len(sec_tokens)) >= 0.6
    )


def parse_sec_ticker_identities(payload: object) -> dict[str, SecTickerIdentity]:
    """Parse official SEC ticker JSON while retaining issuer identity metadata."""
    identities: dict[str, SecTickerIdentity] = {}
    if not isinstance(payload, dict):
        raise ValueError("SEC ticker mapping payload must be an object")

    fields = payload.get("fields")
    data = payload.get("data")
    if isinstance(fields, list) and isinstance(data, list):
        try:
            ticker_index = fields.index("ticker")
            cik_index = fields.index("cik")
            name_index = fields.index("name")
        except ValueError as exc:
            raise ValueError("SEC ticker exchange payload missing ticker, cik, or name fields") from exc
        exchange_index = fields.index("exchange") if "exchange" in fields else None
        for row in data:
            required_indexes = [ticker_index, cik_index, name_index]
            if not isinstance(row, list) or len(row) <= max(required_indexes):
                continue
            ticker = str(row[ticker_index] or "").strip().upper()
            cik = row[cik_index]
            name = str(row[name_index] or "").strip()
            exchange = (
                str(row[exchange_index] or "").strip() or None
                if exchange_index is not None and len(row) > exchange_index
                else None
            )
            if ticker and cik is not None and name:
                identities[ticker] = SecTickerIdentity(
                    ticker=ticker,
                    cik=normalize_cik(cik),
                    name=name,
                    exchange=exchange,
                )
        if not identities:
            raise ValueError("SEC ticker exchange payload contained no ticker mappings")
        return identities

    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        cik = row.get("cik_str")
        name = str(row.get("title") or "").strip()
        if ticker and cik is not None and name:
            identities[ticker] = SecTickerIdentity(
                ticker=ticker,
                cik=normalize_cik(cik),
                name=name,
            )
    if not identities:
        raise ValueError("SEC ticker mapping payload contained no ticker mappings")
    return identities


def parse_sec_ticker_mapping(payload: object) -> dict[str, str]:
    """Parse either official SEC ticker mapping JSON shape into ticker-to-CIK values."""
    return {
        ticker: identity.cik
        for ticker, identity in parse_sec_ticker_identities(payload).items()
    }


def fetch_ticker_identities() -> dict[str, SecTickerIdentity]:
    """Fetch the SEC's official ticker identities with a legacy-shape fallback."""
    headers = _sec_headers()
    last_error: Exception | None = None
    for url in (SEC_TICKER_EXCHANGE_URL, SEC_TICKER_URL):
        try:
            rate_limit_sec()
            response = httpx.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return parse_sec_ticker_identities(response.json())
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            last_error = exc
            logger.warning("Failed to load SEC ticker mapping from %s: %s", url, exc)
    raise RuntimeError(f"Unable to load SEC ticker mappings: {last_error}")


def fetch_ticker_cik_mapping() -> dict[str, str]:
    """Fetch the SEC's official ticker-to-CIK mapping with a legacy-shape fallback."""
    return {ticker: identity.cik for ticker, identity in fetch_ticker_identities().items()}


def parse_sec_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_sec_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        # Convert e.g. "2024-03-20T16:15:00.000Z" to naive UTC datetime
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        return None


def fetch_filings(cik: str | int) -> list[dict]:
    """Fetch filings for a given CIK using SEC Submissions API.

    Only returns tracked forms: 10-K, 10-Q, 8-K, 6-K, 20-F, 40-F.
    Enforces a configured User-Agent and SEC rate limiting.
    """
    # CIK must be padded to 10 digits
    cik_padded = normalize_cik(cik)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    headers = _sec_headers()

    logger.info("Fetching SEC filings for CIK %s from %s", cik_padded, url)
    
    max_retries = 3
    backoff_factor = 2.0
    response = None

    for attempt in range(max_retries):
        try:
            rate_limit_sec()
            response = httpx.get(url, headers=headers, timeout=30.0)
            if response.status_code == 404:
                raise SecSubmissionNotFoundError(cik_padded)
            response.raise_for_status()
            break
        except SecSubmissionNotFoundError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            if attempt == max_retries - 1:
                logger.error("All retry attempts failed for CIK %s: %s", cik_padded, exc)
                raise
            wait = backoff_factor ** (attempt + 1)
            logger.warning("SEC query failed on attempt %d: %s. Retrying in %d seconds...", attempt + 1, exc, wait)
            time.sleep(wait)

    assert response is not None
    data = response.json()

    filings_data = data.get("filings", {})
    recent = filings_data.get("recent", {})
    if not recent or "accessionNumber" not in recent:
        logger.warning("No recent filings found in SEC response for CIK %s", cik_padded)
        return []

    # CIK without leading zeros is used for standard EDGAR Archive URLs
    cik_clean = str(int(cik_padded))

    tracked_forms = {"10-K", "10-Q", "8-K", "6-K", "20-F", "40-F"}
    filings = []

    num_filings = len(recent["accessionNumber"])
    for i in range(num_filings):
        form = recent["form"][i]
        if form not in tracked_forms:
            continue

        accession_no = recent["accessionNumber"][i]
        filing_date_str = recent["filingDate"][i]
        acceptance_dt_str = recent["acceptanceDateTime"][i]
        primary_doc = recent["primaryDocument"][i]

        accession_no_no_dashes = accession_no.replace("-", "")

        filing_detail_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/"
            f"{accession_no_no_dashes}/{accession_no}-index.htm"
        )
        primary_doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/"
            f"{accession_no_no_dashes}/{primary_doc}"
        )

        filings.append({
            "accession_no": accession_no,
            "form": form,
            "filing_date": parse_sec_date(filing_date_str),
            "acceptance_datetime": parse_sec_datetime(acceptance_dt_str),
            "primary_doc_url": primary_doc_url,
            "filing_detail_url": filing_detail_url,
        })

    logger.info("Found %d tracked filings for CIK %s", len(filings), cik_padded)
    return filings
