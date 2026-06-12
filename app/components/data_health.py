from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from argus.core.timezones import format_et_datetime


@dataclass(frozen=True)
class FreshnessCard:
    title: str
    display_value: str
    status: str


@dataclass(frozen=True)
class StaleDataset:
    name: str
    reason: str
    command: str


@dataclass(frozen=True)
class FreshnessSummary:
    stale_items: list[StaleDataset]
    cards: list[FreshnessCard]


FRESHNESS_CARD_CSS = """
            <style>
            .freshness-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 16px;
                margin-top: 12px;
                margin-bottom: 20px;
            }
            .freshness-card {
                background: linear-gradient(135deg, rgba(22, 27, 34, 0.4) 0%, rgba(17, 22, 29, 0.5) 100%);
                border: 1px solid rgba(240, 246, 252, 0.1);
                border-radius: 10px;
                padding: 14px 16px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }
            .freshness-card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .freshness-title {
                font-size: 11px;
                color: #8b949e;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }
            .status-indicator {
                display: inline-flex;
                align-items: center;
                font-size: 10px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                padding: 2px 8px;
                border-radius: 12px;
            }
            .status-indicator.fresh {
                color: #3fb950;
                background: rgba(46, 160, 67, 0.12);
                border: 1px solid rgba(46, 160, 67, 0.2);
            }
            .status-indicator.stale {
                color: #f85149;
                background: rgba(248, 81, 73, 0.12);
                border: 1px solid rgba(248, 81, 73, 0.2);
            }
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                margin-right: 5px;
                display: inline-block;
            }
            .status-indicator.fresh .status-dot {
                background-color: #3fb950;
                box-shadow: 0 0 6px rgba(46, 160, 67, 0.8);
            }
            .status-indicator.stale .status-dot {
                background-color: #f85149;
                box-shadow: 0 0 6px rgba(248, 81, 73, 0.8);
            }
            .freshness-value {
                display: flex;
                align-items: baseline;
                flex-wrap: wrap;
                margin-top: 4px;
            }
            .freshness-val-date {
                font-size: 14px;
                font-weight: 600;
                color: #f0f6fc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }
            .freshness-val-time {
                font-size: 12px;
                color: #8b949e;
                margin-left: 6px;
                font-weight: 400;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }
            .freshness-val-na {
                font-size: 14px;
                font-weight: 600;
                color: #484f58;
            }
            @media (max-width: 768px) {
                .freshness-grid {
                    grid-template-columns: 1fr;
                }
            }
            </style>
            """


def build_freshness_summary(
    health_data: dict[str, pd.DataFrame],
    today: date,
) -> FreshnessSummary:
    latest_values = {
        "prices": _safe_get_val(health_data["latest_prices"]),
        "metrics": _safe_get_val(health_data["latest_metrics"]),
        "macro": _safe_get_val(health_data["latest_macro"]),
        "news": _safe_get_val(health_data["latest_news"]),
        "filings": _safe_get_val(health_data["latest_filings"]),
        "signals": _safe_get_val(health_data["latest_signals"]),
    }
    latest_dates = {key: _parse_date(value) for key, value in latest_values.items()}
    stale_threshold = today - timedelta(days=3)

    stale_items: list[StaleDataset] = []
    datasets = [
        ("Price Bars", latest_dates["prices"], "python scripts/run_daily_refresh.py"),
        ("Daily Metrics", latest_dates["metrics"], "python scripts/compute_metrics.py"),
        ("Macro Observations", latest_dates["macro"], "python scripts/refresh_macro.py"),
        ("News Items", latest_dates["news"], "python scripts/refresh_news.py"),
        ("SEC Filings", latest_dates["filings"], "python scripts/refresh_filings.py"),
        ("Daily Signals", latest_dates["signals"], "python scripts/compute_signals.py"),
    ]
    for name, latest_date, command in datasets:
        if latest_date is None:
            stale_items.append(StaleDataset(name, "No data present", command))
        elif latest_date < stale_threshold:
            stale_items.append(
                StaleDataset(
                    name,
                    f"Stale since {latest_date.isoformat()} (Older than 3 days)",
                    command,
                )
            )

    cards = [
        FreshnessCard(
            "Latest Prices",
            _price_display(health_data["latest_prices"]),
            _freshness_status(latest_dates["prices"], stale_threshold),
        ),
        FreshnessCard(
            "Latest Metrics",
            _format_freshness_val(latest_values["metrics"], is_datetime=False),
            _freshness_status(latest_dates["metrics"], stale_threshold),
        ),
        FreshnessCard(
            "Latest Signals",
            _format_freshness_val(latest_values["signals"], is_datetime=False),
            _freshness_status(latest_dates["signals"], stale_threshold),
        ),
        FreshnessCard(
            "Latest News",
            _format_freshness_val(latest_values["news"], is_datetime=True),
            _freshness_status(latest_dates["news"], stale_threshold),
        ),
        FreshnessCard(
            "Latest Filings",
            _filings_display(health_data["latest_filings"]),
            _freshness_status(latest_dates["filings"], stale_threshold),
        ),
        FreshnessCard(
            "Latest Macro",
            _format_freshness_val(latest_values["macro"], is_datetime=False),
            _freshness_status(latest_dates["macro"], stale_threshold),
        ),
    ]
    return FreshnessSummary(stale_items=stale_items, cards=cards)


def render_freshness_card_html(card: FreshnessCard) -> str:
    if not card.display_value or card.display_value == "N/A":
        value_html = '<span class="freshness-val-na">N/A</span>'
    else:
        parts = card.display_value.split(" ", 1)
        if len(parts) == 2:
            date_part, time_part = parts
            value_html = (
                f'<span class="freshness-val-date">{date_part}</span>'
                f'<span class="freshness-val-time">{time_part}</span>'
            )
        else:
            value_html = f'<span class="freshness-val-date">{card.display_value}</span>'

    status_label = "Fresh" if card.status == "fresh" else "Stale"
    return f"""
            <div class="freshness-card {card.status}">
                <div class="freshness-card-header">
                    <span class="freshness-title">{card.title}</span>
                    <span class="status-indicator {card.status}">
                        <span class="status-dot"></span>
                        {status_label}
                    </span>
                </div>
                <div class="freshness-value">
                    {value_html}
                </div>
            </div>
            """


def render_freshness_grid_html(cards: list[FreshnessCard]) -> str:
    return f"""
            <div class="freshness-grid">
                {"".join(render_freshness_card_html(card) for card in cards)}
            </div>
            """


def _safe_get_val(df: pd.DataFrame | None, col: str = "val"):
    if df is None or df.empty or len(df) == 0:
        return None
    return df.at[0, col]


def _parse_date(val) -> date | None:
    if val is None or pd.isna(val):
        return None
    return pd.to_datetime(val).date()


def _format_freshness_val(val, is_datetime: bool = False) -> str:
    if val is None or pd.isna(val):
        return "N/A"
    if is_datetime:
        formatted = format_et_datetime(val)
        return formatted if formatted != "Never" else str(val)
    try:
        dt = pd.to_datetime(val)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(val)


def _freshness_status(latest_date: date | None, stale_threshold: date) -> str:
    return "stale" if latest_date is None or latest_date < stale_threshold else "fresh"


def _price_display(latest_prices: pd.DataFrame) -> str:
    if latest_prices.empty:
        return "N/A"
    row = latest_prices.iloc[0]
    return _format_freshness_val(row["val"], is_datetime=row.get("interval") == "15m")


def _filings_display(latest_filings: pd.DataFrame) -> str:
    if latest_filings.empty:
        return "N/A"
    row = latest_filings.iloc[0]
    return _format_freshness_val(row["val"], is_datetime=bool(row.get("has_time")))
