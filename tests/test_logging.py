from __future__ import annotations

from io import StringIO
import logging

from argus.core.logging import REDACTED, RedactingFormatter, redact_sensitive_text


def test_redact_sensitive_query_parameters() -> None:
    message = (
        "HTTP Request: GET "
        "https://api.eia.gov/v2/data/?api_key=eia-secret&frequency=monthly "
        "https://api.stlouisfed.org/fred?series_id=DGS10&api_key=fred-secret"
    )

    redacted = redact_sensitive_text(message)

    assert "eia-secret" not in redacted
    assert "fred-secret" not in redacted
    assert f"api_key={REDACTED}" in redacted
    assert "frequency=monthly" in redacted
    assert "series_id=DGS10" in redacted


def test_redact_environment_assignments_and_bearer_tokens() -> None:
    message = (
        "FRED_API_KEY=fred-secret, EIA_API_KEY: eia-secret; "
        "Authorization: Bearer bearer-secret"
    )

    redacted = redact_sensitive_text(message)

    assert "fred-secret" not in redacted
    assert "eia-secret" not in redacted
    assert "bearer-secret" not in redacted
    assert redacted.count(REDACTED) == 3


def test_formatter_redacts_http_exception_traceback() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("argus.test.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        raise RuntimeError(
            "request failed: https://example.test/data?api_key=traceback-secret"
        )
    except RuntimeError:
        logger.exception("Provider request failed")

    output = stream.getvalue()
    assert "traceback-secret" not in output
    assert f"api_key={REDACTED}" in output
