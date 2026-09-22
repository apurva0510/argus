"""Append-only history of user watch-status decisions."""

from sqlalchemy.orm import Session

from argus.core.db import session_scope
from argus.core.models import WatchStatusEvent


def record_watch_status_change(
    session: Session,
    company_id: int,
    previous_status: str,
    new_status: str,
    *,
    reason: str | None,
    source: str,
) -> None:
    if previous_status == new_status:
        return
    session.add(
        WatchStatusEvent(
            company_id=company_id,
            previous_status=previous_status,
            new_status=new_status,
            reason=(reason or "").strip() or None,
            source=source,
        )
    )


def get_watch_status_history(company_id: int, *, limit: int = 20) -> list[dict]:
    with session_scope() as session:
        events = (
            session.query(WatchStatusEvent)
            .filter(WatchStatusEvent.company_id == company_id)
            .order_by(WatchStatusEvent.changed_at.desc(), WatchStatusEvent.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "changed_at": event.changed_at,
                "previous_status": event.previous_status,
                "new_status": event.new_status,
                "reason": event.reason,
                "source": event.source,
            }
            for event in events
        ]
