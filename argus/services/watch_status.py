"""Company-wide watch status decisions stored on watchlist memberships."""

from argus.core.models import WatchlistItem
from argus.core.seed import WATCH_STATUSES
from argus.services.watch_status_history import record_watch_status_change

STATUS_PRIORITY = {"high_priority": 4, "owned": 3, "watch": 2, "ignore": 1}


def validate_watch_status(status: str) -> None:
    if status not in WATCH_STATUSES:
        raise ValueError(f"Invalid watch_status '{status}'")


def resolved_watch_status(items: list[WatchlistItem]) -> str:
    """Resolve legacy conflicting memberships with the most attentive status."""
    return max((item.watch_status for item in items), key=STATUS_PRIORITY.get, default="watch")


def set_company_watch_status(
    session, company_id: int, status: str, *, reason: str | None, source: str,
    items: list[WatchlistItem] | None = None,
) -> None:
    validate_watch_status(status)
    if items is None:
        items = session.query(WatchlistItem).filter(WatchlistItem.company_id == company_id).all()
    previous = resolved_watch_status(items)
    record_watch_status_change(session, company_id, previous, status, reason=reason, source=source)
    for item in items:
        item.watch_status = status
