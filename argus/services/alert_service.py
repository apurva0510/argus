from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from argus.alerts import rule_registry
from argus.core.db import session_scope
from argus.core.models import Alert, AlertEvent

ALERT_RULE_TYPES = rule_registry.ALERT_RULE_TYPES
ALERT_DIRECTIONS = rule_registry.ALERT_DIRECTIONS
ALERT_FORM_TYPES = rule_registry.ALERT_FORM_TYPES
validate_alert_config = rule_registry.validate_alert_config


def get_all_alerts(engine: Engine) -> pd.DataFrame:
    """Fetch all alerts configured in the database, including ticker/watchlist info."""
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                """
                SELECT 
                    a.id,
                    a.name,
                    a.rule_type,
                    c.symbol AS ticker,
                    w.name AS watchlist,
                    a.is_enabled,
                    a.last_triggered_at,
                    a.channel,
                    a.destination,
                    a.config_json
                FROM alerts a
                LEFT JOIN companies c ON c.id = a.company_id
                LEFT JOIN watchlists w ON w.id = a.watchlist_id
                ORDER BY a.name
                """
            ),
            conn,
        )
    return df


def get_recent_alert_events(engine: Engine, limit: int = 50) -> pd.DataFrame:
    """Fetch recent alert trigger history events."""
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                """
                SELECT 
                    ae.id,
                    a.name AS alert_name,
                    ae.event_type,
                    c.symbol AS ticker,
                    ae.triggered_at,
                    ae.delivery_status,
                    ae.payload_json
                FROM alert_events ae
                JOIN alerts a ON a.id = ae.alert_id
                LEFT JOIN companies c ON c.id = ae.company_id
                ORDER BY ae.triggered_at DESC
                LIMIT :limit
                """
            ),
            conn,
            params={"limit": limit},
        )
    return df


def create_alert(
    name: str,
    rule_type: str,
    company_id: int | None = None,
    watchlist_id: int | None = None,
    config_json: dict | None = None,
    channel: str = "email",
    destination: str | None = None,
    is_enabled: bool = True,
) -> int:
    """Create a new alert in the database."""
    validated_config = validate_alert_config(rule_type, config_json)
    if company_id is None and watchlist_id is None:
        raise ValueError("Alert must target a company or watchlist.")

    with session_scope() as session:
        alert = Alert(
            name=name,
            rule_type=rule_type,
            company_id=company_id,
            watchlist_id=watchlist_id,
            config_json=validated_config,
            channel=channel,
            destination=destination,
            is_enabled=is_enabled,
        )
        session.add(alert)
        session.flush()
        return alert.id


def toggle_alert(alert_id: int, is_enabled: bool) -> bool:
    """Enable or disable an alert."""
    with session_scope() as session:
        alert = session.get(Alert, alert_id)
        if alert:
            alert.is_enabled = is_enabled
            return True
        return False


def delete_alert(alert_id: int) -> bool:
    """Delete an alert and all associated alert events from the database."""
    with session_scope() as session:
        session.query(AlertEvent).filter(AlertEvent.alert_id == alert_id).delete()
        alert = session.get(Alert, alert_id)
        if alert:
            session.delete(alert)
            return True
        return False
