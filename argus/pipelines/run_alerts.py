from __future__ import annotations

from datetime import UTC, datetime
import logging
from sqlalchemy import select
from argus.core.db import session_scope
from argus.core.models import (
    Alert,
    AlertEvent,
    Company,
    WatchlistItem,
)
from argus.pipelines.job_runs import create_job_run, finish_job_run
from argus.alerts.rules import evaluate_alert_for_company
from argus.alerts.formatting import format_alert_email
from argus.alerts.email_delivery import is_smtp_configured, send_email

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)





def run_alerts() -> dict[str, object]:
    """Orchestrate alert rules evaluation and notification dispatch.

    Reads active alerts, resolves targets, evaluates rules, checks deduplication
    keys, updates database, and sends email notifications.
    """
    job_id = create_job_run("run_alerts")
    rows_read = 0
    rows_written = 0
    status = "success"
    error_text: str | None = None

    try:
        smtp_ok = is_smtp_configured()
        if not smtp_ok:
            logger.info(
                "SMTP email delivery is not configured; triggered events will be saved as 'skipped'."
            )

        with session_scope() as session:
            # 1. Fetch enabled alerts
            active_alerts = session.scalars(select(Alert).where(Alert.is_enabled.is_(True))).all()

            for alert in active_alerts:
                # 2. Resolve companies for this alert
                companies_to_check: list[Company] = []
                if alert.company_id is not None:
                    c = session.get(Company, alert.company_id)
                    if c and c.is_active:
                        companies_to_check.append(c)
                elif alert.watchlist_id is not None:
                    company_rows = (
                        session.query(Company)
                        .join(WatchlistItem, WatchlistItem.company_id == Company.id)
                        .filter(
                            WatchlistItem.watchlist_id == alert.watchlist_id,
                            Company.is_active.is_(True),
                        )
                        .all()
                    )
                    companies_to_check.extend(company_rows)

                # Evaluate for each company
                for company in companies_to_check:
                    rows_read += 1
                    triggers = evaluate_alert_for_company(session, alert, company)
                    if not triggers:
                        continue

                    for payload in triggers:
                        # 3. Generate dedupe key
                        # Price/technical rules use date
                        if alert.rule_type == "new_sec_filing":
                            acc_no = payload.get("accession_no", "unknown")
                            dedupe_key = f"alert:{alert.id}:company:{company.id}:filing:{acc_no}"
                        elif alert.rule_type == "news_keyword_match":
                            news_id = payload.get("news_id", "unknown")
                            dedupe_key = f"alert:{alert.id}:company:{company.id}:news:{news_id}"
                        elif alert.rule_type == "earnings_within_days":
                            event_date = payload.get("event_date", "unknown")
                            dedupe_key = (
                                f"alert:{alert.id}:company:{company.id}:earnings:{event_date}"
                            )
                        else:
                            metric_date = payload.get("date") or _utc_now().date().isoformat()
                            dedupe_key = f"alert:{alert.id}:company:{company.id}:date:{metric_date}"

                        # 4. Check for existing AlertEvent with this dedupe key
                        existing = (
                            session.query(AlertEvent)
                            .filter(AlertEvent.dedupe_key == dedupe_key)
                            .first()
                        )
                        if existing:
                            # Already sent / recorded, skip!
                            continue

                        # 5. Dispatch Notification
                        delivery_status = "skipped"
                        if smtp_ok:
                            try:
                                subject, txt_body, html_body = format_alert_email(
                                    alert, company, payload
                                )
                                mail_sent = send_email(subject, txt_body, html_body)
                                delivery_status = "sent" if mail_sent else "failed"
                            except Exception:
                                logger.exception(
                                    "Error formatting or sending email for alert %s, company %s",
                                    alert.id,
                                    company.symbol,
                                )
                                delivery_status = "failed"
                        else:
                            delivery_status = "skipped"

                        # 6. Save AlertEvent
                        event = AlertEvent(
                            alert_id=alert.id,
                            company_id=company.id,
                            event_type=alert.rule_type,
                            payload_json=payload,
                            delivery_status=delivery_status,
                            dedupe_key=dedupe_key,
                            triggered_at=_utc_now(),
                        )
                        session.add(event)

                        # Update alert trigger timestamp
                        alert.last_triggered_at = _utc_now()
                        rows_written += 1

    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Alert pipeline runner failed")
    finally:
        finish_job_run(
            job_id,
            "run_alerts",
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "error_text": error_text,
    }
