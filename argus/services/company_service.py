from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from argus.core.db import session_scope
from argus.core.models import (
    Company,
    DailyMetric,
    FundamentalsSnapshot,
    NewsItem,
    NewsMention,
    PriceBar,
    SecFiling,
    UserNote,
    Watchlist,
    WatchlistItem,
)


def get_company_options() -> list[str]:
    with session_scope() as session:
        symbols = session.query(Company.symbol).filter(Company.is_active.is_(True)).order_by(Company.symbol).all()
    return [row[0] for row in symbols]


def get_company_by_symbol(symbol: str) -> dict | None:
    with session_scope() as session:
        company = session.query(Company).filter(Company.symbol == symbol, Company.is_active.is_(True)).one_or_none()
        if not company:
            return None
        return {
            "id": company.id,
            "symbol": company.symbol,
            "name": company.name,
            "exchange": company.exchange,
            "sector": company.sector,
            "industry": company.industry,
            "country": company.country,
            "cik": company.cik,
            "is_benchmark": company.is_benchmark,
            "is_hyperscaler": company.is_hyperscaler,
        }


def get_company_metrics(company_id: int) -> dict | None:
    with session_scope() as session:
        metric = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == company_id)
            .order_by(DailyMetric.date.desc())
            .first()
        )
        if not metric:
            return None
        return {
            "date": metric.date,
            "return_1d": metric.return_1d,
            "return_1w": metric.return_1w,
            "return_1m": metric.return_1m,
            "return_3m": metric.return_3m,
            "return_6m": metric.return_6m,
            "return_ytd": metric.return_ytd,
            "ma_50": metric.ma_50,
            "ma_200": metric.ma_200,
            "rsi_14": metric.rsi_14,
            "high_52w": metric.high_52w,
            "low_52w": metric.low_52w,
            "drawdown_52w": metric.drawdown_52w,
            "distance_from_50dma": metric.distance_from_50dma,
            "distance_from_200dma": metric.distance_from_200dma,
            "relative_return_vs_qqq_1m": metric.relative_return_vs_qqq_1m,
            "relative_return_vs_qqq_3m": metric.relative_return_vs_qqq_3m,
            "relative_return_vs_nvda_1m": metric.relative_return_vs_nvda_1m,
            "relative_return_vs_nvda_3m": metric.relative_return_vs_nvda_3m,
            "volatility_20d": metric.volatility_20d,
            "opportunity_score": metric.opportunity_score,
        }


def get_company_price_history(company_id: int) -> pd.DataFrame:
    with session_scope() as session:
        query = (
            session.query(PriceBar)
            .filter(PriceBar.company_id == company_id, PriceBar.provider == "yfinance", PriceBar.interval == "1d")
            .order_by(PriceBar.date.asc())
        )
        df = pd.read_sql_query(query.statement, session.bind)
        return df


def get_company_fundamentals(company_id: int) -> dict | None:
    with session_scope() as session:
        fundamental = (
            session.query(FundamentalsSnapshot)
            .filter(FundamentalsSnapshot.company_id == company_id)
            .order_by(FundamentalsSnapshot.as_of_date.desc())
            .first()
        )
        if not fundamental:
            return None
        return {
            "as_of_date": fundamental.as_of_date,
            "market_cap": fundamental.market_cap,
            "enterprise_value": fundamental.enterprise_value,
            "trailing_pe": fundamental.trailing_pe,
            "forward_pe": fundamental.forward_pe,
            "price_to_sales": fundamental.price_to_sales,
            "ev_to_sales": fundamental.ev_to_sales,
            "ev_to_ebitda": fundamental.ev_to_ebitda,
            "revenue_growth": fundamental.revenue_growth,
            "gross_margin": fundamental.gross_margin,
            "operating_margin": fundamental.operating_margin,
            "free_cash_flow": fundamental.free_cash_flow,
            "provider": fundamental.provider,
        }


def get_company_news(company_id: int, limit: int = 10) -> list[dict]:
    with session_scope() as session:
        results = (
            session.query(NewsItem)
            .join(NewsMention, NewsMention.news_id == NewsItem.id)
            .filter(NewsMention.company_id == company_id)
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "published_at": item.published_at,
                "title": item.title,
                "summary": item.summary,
                "url": item.url,
                "source_name": item.source_name,
            }
            for item in results
        ]


def get_company_filings(company_id: int, limit: int = 10) -> list[dict]:
    with session_scope() as session:
        results = (
            session.query(SecFiling)
            .filter(SecFiling.company_id == company_id)
            .order_by(SecFiling.filing_date.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "filing_date": f.filing_date,
                "form": f.form,
                "primary_doc_url": f.primary_doc_url,
                "filing_detail_url": f.filing_detail_url,
            }
            for f in results
        ]


def get_company_notes(company_id: int) -> list[dict]:
    with session_scope() as session:
        results = (
            session.query(UserNote)
            .filter(UserNote.company_id == company_id)
            .order_by(UserNote.created_at.desc())
            .all()
        )
        return [
            {
                "id": note.id,
                "note_text": note.note_text,
                "note_type": note.note_type,
                "created_by": note.created_by,
                "created_at": note.created_at,
            }
            for note in results
        ]


def add_company_note(
    company_id: int,
    note_text: str,
    note_type: str | None = None,
    created_by: str | None = "User",
) -> None:
    if not note_text.strip():
        return
    with session_scope() as session:
        note = UserNote(
            company_id=company_id,
            note_text=note_text.strip(),
            note_type=note_type,
            created_by=created_by,
        )
        session.add(note)
        
        # Sync notes to all watchlist_items for this company
        items = session.query(WatchlistItem).filter(WatchlistItem.company_id == company_id).all()
        for item in items:
            item.notes = note_text.strip()


def get_watch_status(company_id: int) -> str:
    with session_scope() as session:
        item = (
            session.query(WatchlistItem)
            .filter(WatchlistItem.company_id == company_id)
            .first()
        )
        return item.watch_status if item else "watch"


def update_watch_status(company_id: int, watch_status: str) -> None:
    with session_scope() as session:
        items = (
            session.query(WatchlistItem)
            .filter(WatchlistItem.company_id == company_id)
            .all()
        )
        if items:
            for item in items:
                item.watch_status = watch_status
        else:
            # Associate company with its sector watchlist or first watchlist
            company = session.query(Company).filter(Company.id == company_id).one_or_none()
            if not company:
                return
            wl = None
            if company.sector:
                wl = session.query(Watchlist).filter(Watchlist.name == company.sector).first()
            if not wl:
                wl = session.query(Watchlist).first()
            if not wl:
                wl = Watchlist(name="General Watchlist", description="General watchlist for all stocks")
                session.add(wl)
                session.flush()
            
            item = WatchlistItem(
                watchlist_id=wl.id,
                company_id=company_id,
                watch_status=watch_status,
                notes="",
            )
            session.add(item)


def get_watchlist_notes(company_id: int) -> list[dict]:
    with session_scope() as session:
        results = (
            session.query(Watchlist.name, WatchlistItem.notes)
            .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
            .filter(WatchlistItem.company_id == company_id)
            .all()
        )
        return [{"watchlist": row[0], "notes": row[1]} for row in results if row[1] and row[1].strip()]
