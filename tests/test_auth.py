from argus.core.auth import create_auth_token, validate_auth_token
from app.auth_links import company_detail_url


def test_auth_token_validates_with_same_secret() -> None:
    token = create_auth_token("secret", now=1_000, ttl_seconds=60)

    assert validate_auth_token(token, "secret", now=1_030)


def test_auth_token_rejects_forged_legacy_cookie_value() -> None:
    assert not validate_auth_token("1", "secret", now=1_000)


def test_auth_token_rejects_wrong_secret() -> None:
    token = create_auth_token("secret", now=1_000, ttl_seconds=60)

    assert not validate_auth_token(token, "different-secret", now=1_030)


def test_auth_token_rejects_expired_token() -> None:
    token = create_auth_token("secret", now=1_000, ttl_seconds=60)

    assert not validate_auth_token(token, "secret", now=1_061)


def test_company_detail_url_does_not_expose_auth_token() -> None:
    assert company_detail_url("NVDA") == "/Company_Detail?ticker=NVDA"


def test_default_auth_token_ttl_is_six_hours() -> None:
    from argus.core.auth import DEFAULT_AUTH_TTL_SECONDS
    assert DEFAULT_AUTH_TTL_SECONDS == 21600

    token = create_auth_token("secret", now=1_000)
    assert validate_auth_token(token, "secret", now=1_000 + 21540)
    assert not validate_auth_token(token, "secret", now=1_000 + 21601)
