from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from argus.core.db import session_scope
from argus.core.models import Alert, AlertEvent

ALERT_RULE_TYPES = {
    "price_below",
    "price_above",
    "daily_move_gt",
    "drawdown_52w_gt",
    "rsi_below",
    "crossed_50dma",
    "crossed_200dma",
    "new_sec_filing",
    "news_keyword_match",
    "earnings_within_days",
    "entered_pullback_zone",
}
ALERT_DIRECTIONS = {"any", "above", "below"}
ALERT_FORM_TYPES = {"10-K", "10-Q", "8-K", "6-K", "20-F", "40-F"}


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


def validate_alert_config(rule_type: str, config_json: dict | None) -> dict | None:
    if rule_type not in ALERT_RULE_TYPES:
        raise ValueError(f"Unknown alert rule type: {rule_type}")

    config = config_json or {}
    if rule_type in {"price_below", "price_above", "rsi_below"}:
        return {"threshold": _required_float(config, "threshold")}
    if rule_type in {"daily_move_gt", "drawdown_52w_gt"}:
        return {"threshold_pct": _required_float(config, "threshold_pct")}
    if rule_type in {"crossed_50dma", "crossed_200dma"}:
        direction = str(config.get("direction", "any")).strip().lower()
        if direction not in ALERT_DIRECTIONS:
            raise ValueError("direction must be one of: any, above, below")
        return {"direction": direction}
    if rule_type == "new_sec_filing":
        forms = config.get("forms")
        if not forms:
            return None
        if isinstance(forms, str):
            forms = [forms]
        cleaned_forms = [str(form).strip().upper() for form in forms if str(form).strip()]
        invalid_forms = [form for form in cleaned_forms if form not in ALERT_FORM_TYPES]
        if invalid_forms:
            raise ValueError(f"Unsupported SEC form type(s): {', '.join(invalid_forms)}")
        return {"forms": cleaned_forms} if cleaned_forms else None
    if rule_type == "news_keyword_match":
        keywords = config.get("keywords")
        if keywords is None:
            return None
        if isinstance(keywords, str):
            cleaned_keywords = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        else:
            cleaned_keywords = [str(kw).strip() for kw in keywords if str(kw).strip()]
        return {"keywords": cleaned_keywords} if cleaned_keywords else None
    if rule_type == "earnings_within_days":
        days = int(_required_float(config, "days"))
        if days < 1:
            raise ValueError("days must be at least 1")
        return {"days": days}
    if rule_type == "entered_pullback_zone":
        return {
            "min_drawdown_pct": _optional_float(config, "min_drawdown_pct", 10.0),
            "max_rsi": _optional_float(config, "max_rsi", 55.0),
            "min_distance_from_200dma": _optional_float(config, "min_distance_from_200dma", -5.0),
        }
    return None


def _required_float(config: dict, key: str) -> float:
    if key not in config or config[key] is None:
        raise ValueError(f"{key} is required")
    return _coerce_float(config[key], key)


def _optional_float(config: dict, key: str, default: float) -> float:
    value = config.get(key, default)
    return _coerce_float(value, key)


def _coerce_float(value, key: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc


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
