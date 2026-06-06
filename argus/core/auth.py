from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


AUTH_COOKIE_NAME = "app_password_auth"
AUTH_QUERY_PARAM = "auth"
DEFAULT_AUTH_TTL_SECONDS = 6 * 60 * 60


def create_auth_token(
    secret: str, *, now: int | None = None, ttl_seconds: int = DEFAULT_AUTH_TTL_SECONDS
) -> str:
    if not secret:
        raise ValueError("Auth token secret must not be blank")

    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + ttl_seconds
    payload = f"{expires_at}:{secrets.token_urlsafe(16)}"
    signature = _sign(payload, secret)
    encoded_payload = _b64encode(payload.encode("utf-8"))
    return f"{encoded_payload}.{signature}"


def validate_auth_token(token: str | None, secret: str, *, now: int | None = None) -> bool:
    if not token or not secret or "." not in token:
        return False

    encoded_payload, supplied_signature = token.split(".", 1)
    try:
        payload = _b64decode(encoded_payload).decode("utf-8")
        expires_at_raw, _ = payload.split(":", 1)
        expires_at = int(expires_at_raw)
    except (ValueError, UnicodeDecodeError):
        return False

    expected_signature = _sign(payload, secret)
    current_time = int(now if now is not None else time.time())
    return (
        hmac.compare_digest(supplied_signature, expected_signature) and current_time <= expires_at
    )


def append_auth_token_to_url(url: str, token: str | None) -> str:
    """Append a signed auth token to an internal link without altering existing query values."""
    if not token:
        return url

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[AUTH_QUERY_PARAM] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
