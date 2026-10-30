from __future__ import annotations

import logging
import re


REDACTED = "[REDACTED]"

_SENSITIVE_QUERY_PARAMETER = re.compile(
    r"(?P<prefix>[?&](?:api[_-]?key|apikey|access_token|token|client_secret)=)"
    r"(?P<secret>[^&\s]+)",
    flags=re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b(?:FRED_API_KEY|EIA_API_KEY|FINNHUB_API_KEY|"
    r"TWELVE_DATA_API_KEY|ALPHA_VANTAGE_API_KEY)\s*[=:]\s*)"
    r"(?P<secret>[^\s,;]+)",
    flags=re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(
    r"(?P<prefix>\bAuthorization\s*:\s*Bearer\s+)(?P<secret>[^\s,;]+)",
    flags=re.IGNORECASE,
)


def redact_sensitive_text(value: object) -> str:
    """Return log text with common credential forms removed.

    HTTP clients include prepared request URLs in both routine request logs and
    exception messages. Redacting the final formatted record covers both paths.
    """
    text = str(value)
    for pattern in (
        _SENSITIVE_QUERY_PARAMETER,
        _SENSITIVE_ASSIGNMENT,
        _BEARER_TOKEN,
    ):
        text = pattern.sub(rf"\g<prefix>{REDACTED}", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formatter that prevents credentials from reaching any log destination."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    formatter = RedactingFormatter(
        "%(asctime)s %(levelname)s %(name)s - %(message)s"
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
