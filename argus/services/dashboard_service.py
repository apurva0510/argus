from argus.core.db import session_scope
from argus.core.models import Company, DailyMetric, NewsItem, PriceBar, SecFiling, WatchlistItem


def get_dashboard_overview() -> dict[str, int]:
    with session_scope() as session:
        return {
            "tracked_companies": session.query(Company).filter(Company.is_active.is_(True)).count(),
            "high_priority_count": session.query(WatchlistItem).filter(WatchlistItem.watch_status == "high_priority").count(),
            "owned_count": session.query(WatchlistItem).filter(WatchlistItem.watch_status == "owned").count(),
            "price_bar_count": session.query(PriceBar).count(),
            "metrics_count": session.query(DailyMetric).count(),
            "news_count": session.query(NewsItem).count(),
            "filings_count": session.query(SecFiling).count(),
        }
