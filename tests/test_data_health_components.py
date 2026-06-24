from __future__ import annotations

from datetime import date

import pandas as pd

from app.components.data_health import (
    FRESHNESS_CARD_CSS,
    FreshnessCard,
    build_freshness_summary,
    render_freshness_card_html,
    render_freshness_grid_html,
)


def test_build_freshness_summary_marks_fresh_stale_and_missing() -> None:
    summary = build_freshness_summary(
        {
            "latest_prices": pd.DataFrame([{"val": "2026-06-10", "interval": "1d"}]),
            "latest_metrics": pd.DataFrame([{"val": "2026-06-07"}]),
            "latest_macro": pd.DataFrame(columns=["val"]),
            "latest_news": pd.DataFrame([{"val": "2026-06-10 15:30:00"}]),
            "latest_filings": pd.DataFrame([{"val": "2026-06-01", "has_time": False}]),
            "latest_signals": pd.DataFrame([{"val": "2026-06-11"}]),
        },
        today=date(2026, 6, 11),
    )

    stale_by_name = {item.name: item for item in summary.stale_items}
    assert set(stale_by_name) == {"Daily Metrics", "Macro Observations", "SEC Filings"}
    assert stale_by_name["Daily Metrics"].reason == "Stale since 2026-06-07 (Older than 3 days)"
    assert stale_by_name["Macro Observations"].reason == "No data present"
    assert stale_by_name["SEC Filings"].command == "python scripts/refresh_filings.py"

    cards = {card.title: card for card in summary.cards}
    assert cards["Latest Prices"] == FreshnessCard("Latest Prices", "2026-06-10", "fresh")
    assert cards["Latest Metrics"].status == "stale"
    assert cards["Latest Macro"].display_value == "N/A"
    assert cards["Latest News"].display_value.startswith("2026-06-10")
    assert cards["Latest Filings"].display_value == "2026-06-01"
    assert cards["Latest Signals"].status == "fresh"


def test_build_freshness_summary_formats_intraday_prices_and_timed_filings() -> None:
    summary = build_freshness_summary(
        {
            "latest_prices": pd.DataFrame([{"val": "2026-06-10 20:00:00", "interval": "15m"}]),
            "latest_metrics": pd.DataFrame([{"val": "2026-06-10"}]),
            "latest_macro": pd.DataFrame([{"val": "2026-06-10 19:00:00"}]),
            "latest_news": pd.DataFrame([{"val": "2026-06-10 21:00:00"}]),
            "latest_filings": pd.DataFrame(
                [{"val": "2026-06-10 22:00:00", "has_time": True}]
            ),
            "latest_signals": pd.DataFrame([{"val": "2026-06-10"}]),
        },
        today=date(2026, 6, 11),
    )

    cards = {card.title: card for card in summary.cards}
    assert cards["Latest Prices"].display_value == "2026-06-10 04:00 PM ET"
    assert cards["Latest Filings"].display_value == "2026-06-10 06:00 PM ET"
    assert cards["Latest Macro"].display_value == "2026-06-10 03:00 PM ET"
    assert not summary.stale_items


def test_render_freshness_card_html_splits_date_and_time() -> None:
    html = render_freshness_card_html(
        FreshnessCard("Latest News", "2026-06-10 04:00 PM ET", "fresh")
    )

    assert 'class="freshness-card fresh"' in html
    assert "Latest News" in html
    assert '<span class="freshness-val-date">2026-06-10</span>' in html
    assert '<span class="freshness-val-time">04:00 PM ET</span>' in html


def test_render_freshness_card_html_handles_missing_values() -> None:
    html = render_freshness_card_html(FreshnessCard("Latest Macro", "N/A", "stale"))

    assert 'class="freshness-card stale"' in html
    assert '<span class="freshness-val-na">N/A</span>' in html


def test_render_freshness_grid_html_wraps_cards() -> None:
    html = render_freshness_grid_html(
        [
            FreshnessCard("Latest Prices", "2026-06-10", "fresh"),
            FreshnessCard("Latest Macro", "N/A", "stale"),
        ]
    )

    assert 'class="freshness-grid"' in html
    assert html.count('class="freshness-card fresh"') == 1
    assert html.count('class="freshness-card stale"') == 1
    assert "Latest Prices" in html
    assert "Latest Macro" in html
    assert ".freshness-grid" in FRESHNESS_CARD_CSS
    assert "@media (max-width: 768px)" in FRESHNESS_CARD_CSS
