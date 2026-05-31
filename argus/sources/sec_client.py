import logging
import time
from datetime import UTC, date, datetime
import httpx

from argus.core.settings import settings

logger = logging.getLogger(__name__)

# SEC rate limit is 10 requests per second. The plan specifies no more than 8 requests per second.
# This means at least 0.13 seconds between queries.
SEC_RATE_LIMIT_DELAY = 0.15
_last_request_time = 0.0


def rate_limit_sec() -> None:
    """Enforces rate limit delay between SEC EDGAR requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    wait_time = SEC_RATE_LIMIT_DELAY - elapsed
    if wait_time > 0:
        time.sleep(wait_time)
    _last_request_time = time.time()


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
    user_agent = settings.sec_user_agent
    if not user_agent or not user_agent.strip():
        raise ValueError("SEC_USER_AGENT is not configured. Please set it in environment or .env file.")

    # CIK must be padded to 10 digits
    cik_str = str(cik).strip()
    cik_padded = cik_str.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
    }

    logger.info("Fetching SEC filings for CIK %s from %s", cik_padded, url)
    
    max_retries = 3
    backoff_factor = 2.0
    response = None

    for attempt in range(max_retries):
        try:
            rate_limit_sec()
            response = httpx.get(url, headers=headers, timeout=30.0)
            if response.status_code == 404:
                logger.warning("SEC submissions for CIK %s not found (404). Returning empty.", cik_padded)
                return []
            response.raise_for_status()
            break
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
    cik_clean = str(int(cik_str))

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
