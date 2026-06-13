from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    event,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from argus.core.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(32))
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64))
    cik: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_benchmark: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hyperscaler: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Theme(Base):
    __tablename__ = "themes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_theme_id: Mapped[int | None] = mapped_column(ForeignKey("themes.id"))


class CompanyThemeExposure(Base):
    __tablename__ = "company_theme_exposure"
    __table_args__ = (UniqueConstraint("company_id", "theme_id", name="uq_company_theme_exposure"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id"), index=True, nullable=False)
    exposure_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    as_of_date: Mapped[date | None] = mapped_column(Date)


class Watchlist(Base, TimestampMixin):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "company_id", name="uq_watchlist_items"),
        CheckConstraint(
            "watch_status IN ('ignore', 'watch', 'high_priority', 'owned')",
            name="ck_watchlist_items_watch_status",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id"), index=True, nullable=False
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    watch_status: Mapped[str] = mapped_column(String(32), default="watch", nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("company_id", "bar_time", "provider", "interval", name="uq_price_bars"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(32), default="yfinance", nullable=False)
    interval: Mapped[str] = mapped_column(String(16), default="1d", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


@event.listens_for(PriceBar, "before_insert")
def _set_price_bar_bar_time(_mapper, _connection, target: PriceBar) -> None:
    if target.bar_time is None:
        target.bar_time = datetime.combine(target.date, time.min)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_daily_metrics"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    return_1d: Mapped[float | None] = mapped_column(Float)
    return_1w: Mapped[float | None] = mapped_column(Float)
    return_1m: Mapped[float | None] = mapped_column(Float)
    return_3m: Mapped[float | None] = mapped_column(Float)
    return_6m: Mapped[float | None] = mapped_column(Float)
    return_ytd: Mapped[float | None] = mapped_column(Float)
    ma_50: Mapped[float | None] = mapped_column(Float)
    ma_200: Mapped[float | None] = mapped_column(Float)
    rsi_14: Mapped[float | None] = mapped_column(Float)
    high_52w: Mapped[float | None] = mapped_column(Float)
    low_52w: Mapped[float | None] = mapped_column(Float)
    drawdown_52w: Mapped[float | None] = mapped_column(Float)
    distance_from_50dma: Mapped[float | None] = mapped_column(Float)
    distance_from_200dma: Mapped[float | None] = mapped_column(Float)
    relative_return_vs_qqq_1m: Mapped[float | None] = mapped_column(Float)
    relative_return_vs_qqq_3m: Mapped[float | None] = mapped_column(Float)
    relative_return_vs_nvda_1m: Mapped[float | None] = mapped_column(Float)
    relative_return_vs_nvda_3m: Mapped[float | None] = mapped_column(Float)
    volatility_20d: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class FundamentalsSnapshot(Base):
    __tablename__ = "fundamentals_snapshot"
    __table_args__ = (
        UniqueConstraint("company_id", "as_of_date", "provider", name="uq_fundamentals_snapshot"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    market_cap: Mapped[float | None] = mapped_column(Float)
    enterprise_value: Mapped[float | None] = mapped_column(Float)
    trailing_pe: Mapped[float | None] = mapped_column(Float)
    forward_pe: Mapped[float | None] = mapped_column(Float)
    price_to_sales: Mapped[float | None] = mapped_column(Float)
    ev_to_sales: Mapped[float | None] = mapped_column(Float)
    ev_to_ebitda: Mapped[float | None] = mapped_column(Float)
    revenue_growth: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    operating_margin: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(32), default="yfinance", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class NewsItem(Base):
    __tablename__ = "news_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[str | None] = mapped_column(String(64))
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    sentiment_explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class NewsMention(Base):
    __tablename__ = "news_mentions"
    __table_args__ = (UniqueConstraint("news_id", "company_id", name="uq_news_mentions"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True, nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(16))
    is_primary_match: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matched_keywords: Mapped[str | None] = mapped_column(Text)


class SecFiling(Base):
    __tablename__ = "sec_filings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    accession_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    form: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date)
    acceptance_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    primary_doc_url: Mapped[str | None] = mapped_column(String(1024))
    filing_detail_url: Mapped[str | None] = mapped_column(String(1024))
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class EarningsEvent(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (
        UniqueConstraint("company_id", "event_date", "source", name="uq_earnings_events"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    fiscal_period: Mapped[str | None] = mapped_column(String(64))
    eps_estimate: Mapped[float | None] = mapped_column(Float)
    eps_actual: Mapped[float | None] = mapped_column(Float)
    revenue_estimate: Mapped[float | None] = mapped_column(Float)
    revenue_actual: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), default="yfinance", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class IndexValue(Base):
    __tablename__ = "index_values"
    __table_args__ = (UniqueConstraint("index_definition_id", "date", name="uq_index_values"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_definition_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("index_definitions.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    index_value: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class MacroSeries(Base):
    __tablename__ = "macro_series"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="fred", nullable=False)
    frequency: Mapped[str | None] = mapped_column(String(32))
    units: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint("series_code", "observation_date", name="uq_macro_observations"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_code: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("macro_series.code", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    observation_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="fred", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class CapexObservation(Base):
    __tablename__ = "capex_observations"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_period_end", name="uq_capex_observations"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    fiscal_period_end: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    capex_amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlists.id"), index=True)
    config_json: Mapped[dict | None] = mapped_column(JSON)
    channel: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_alert_events_dedupe_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    delivery_status: Mapped[str | None] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class UserNote(Base, TimestampMixin):
    __tablename__ = "user_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(64))


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rows_read: Mapped[int | None] = mapped_column(Integer)
    rows_written: Mapped[int | None] = mapped_column(Integer)
    error_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ProviderHealth(Base):
    __tablename__ = "provider_health"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="healthy", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class ProviderDailyUsage(Base):
    __tablename__ = "provider_daily_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rate_limit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_request_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("provider", "date", name="uq_provider_daily_usage"),)


class SignalDaily(Base):
    __tablename__ = "signal_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    sentiment_proxy_7d: Mapped[float | None] = mapped_column(Float)
    news_relevance_7d: Mapped[float | None] = mapped_column(Float)
    corr_nvda_60d: Mapped[float | None] = mapped_column(Float)
    corr_hyperscaler_60d: Mapped[float | None] = mapped_column(Float)
    earnings_sensitivity: Mapped[float | None] = mapped_column(Float)
    power_signal: Mapped[float | None] = mapped_column(Float)
    capex_signal: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_signal_daily"),)


class MacroReleaseEvent(Base):
    __tablename__ = "macro_release_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("macro_series.code", ondelete="CASCADE"), index=True, nullable=False
    )
    release_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    event_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("series_code", "release_date", name="uq_macro_release_events"),
    )


class IndexDefinition(Base):
    __tablename__ = "index_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)  # 'equal', 'exposure', 'manual'
    base_value: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class IndexConstituent(Base):
    __tablename__ = "index_constituents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_definition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("index_definitions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_included: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("index_definition_id", "company_id", name="uq_index_constituents"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
