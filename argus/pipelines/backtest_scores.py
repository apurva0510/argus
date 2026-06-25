from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import pandas as pd
from sqlalchemy import text
from argus.analytics.scoring import compute_opportunity_score, ScoreInputs
from argus.core.db import session_scope, safe_execute_query
from argus.core.models import ScoreBacktestEvent, ScoreBacktestSummary


logger = logging.getLogger(__name__)


def backtest_opportunity_scores(start_date: date) -> dict[str, int]:
    """Run historical backtest for pullback finder scores from start_date to yesterday.

    For each active company:
      - Compute historical opportunity scores day-by-day.
      - Track forward 5D, 20D, 60D returns and 20D, 60D max drawdowns.
      - Skip recording a new event if it is within 5 trading days of the last recorded event.
      - Save events to score_backtest_events.
      - Re-aggregate metrics and save to score_backtest_summaries.
    """
    yesterday = date.today() - timedelta(days=1)
    if start_date > yesterday:
        logger.info("Start date %s is after yesterday %s. Skipping backtest.", start_date, yesterday)
        return {"events_created": 0}

    with session_scope() as session:
        # 1. Load active companies
        companies = safe_execute_query(
            session,
            "SELECT id, symbol, sector FROM companies WHERE is_active = TRUE"
        )
        company_map = {c["id"]: c for c in companies}
        company_ids = list(company_map.keys())

        if not company_ids:
            logger.warning("No active companies found for backtesting.")
            return {"events_created": 0}

        # 2. Load daily metrics history
        logger.info("Loading daily metrics...")
        metrics_rows = safe_execute_query(
            session,
            f"""
            SELECT id, company_id, date, drawdown_52w, rsi_14, distance_from_200dma,
                   relative_return_vs_qqq_3m, return_1w
            FROM daily_metrics
            WHERE date >= :start_date AND date <= :yesterday AND company_id IN ({','.join(map(str, company_ids))})
            ORDER BY date ASC
            """,
            {"start_date": start_date, "yesterday": yesterday}
        )

        # Group metrics by date
        metrics_by_date = {}
        for m in metrics_rows:
            metrics_by_date.setdefault(m["date"], []).append(m)

        # 3. Load all historical input data into memory for fast lookup
        logger.info("Loading historical inputs...")
        
        # Theme exposures
        cte_rows = safe_execute_query(
            session,
            "SELECT company_id, exposure_score, as_of_date FROM company_theme_exposure"
        )
        cte_by_company = {}
        for row in cte_rows:
            cte_by_company.setdefault(row["company_id"], []).append(row)
        for cid in cte_by_company:
            cte_by_company[cid].sort(key=lambda x: x["as_of_date"] or date.min)

        # News mentions
        news_rows = safe_execute_query(
            session,
            """
            SELECT nm.company_id, ni.published_at
            FROM news_mentions nm
            JOIN news_items ni ON ni.id = nm.news_id
            """
        )
        news_by_company = {}
        for row in news_rows:
            news_by_company.setdefault(row["company_id"], []).append(row["published_at"])
        for cid in news_by_company:
            news_by_company[cid].sort()

        # SEC filings
        filing_rows = safe_execute_query(
            session,
            "SELECT company_id, filing_date FROM sec_filings"
        )
        filing_by_company = {}
        for row in filing_rows:
            filing_by_company.setdefault(row["company_id"], []).append(row["filing_date"])
        for cid in filing_by_company:
            filing_by_company[cid].sort()

        # Earnings events
        earnings_rows = safe_execute_query(
            session,
            "SELECT company_id, event_date FROM earnings_events"
        )
        earnings_by_company = {}
        for row in earnings_rows:
            earnings_by_company.setdefault(row["company_id"], []).append(row["event_date"])
        for cid in earnings_by_company:
            earnings_by_company[cid].sort()

        # Valuation snapshots (ev_to_sales)
        vps_rows = safe_execute_query(
            session,
            """
            SELECT company_id, valuation_flag, as_of_date
            FROM valuation_peer_snapshot
            WHERE peer_group_type = 'sector' AND metric_name = 'ev_to_sales'
            """
        )
        vps_by_company = {}
        for row in vps_rows:
            vps_by_company.setdefault(row["company_id"], []).append(row)
        for cid in vps_by_company:
            vps_by_company[cid].sort(key=lambda x: x["as_of_date"] or date.min)

        # Fundamentals snapshots
        fs_rows = safe_execute_query(
            session,
            "SELECT company_id, revenue_growth, as_of_date FROM fundamentals_snapshot"
        )
        fs_by_company = {}
        for row in fs_rows:
            fs_by_company.setdefault(row["company_id"], []).append(row)
        for cid in fs_by_company:
            fs_by_company[cid].sort(key=lambda x: x["as_of_date"] or date.min)

        # Watchlist priority
        watchlist_rows = safe_execute_query(
            session,
            "SELECT company_id, watch_status FROM watchlist_items"
        )
        watchlist_by_company = {row["company_id"]: row["watch_status"] for row in watchlist_rows}

        # 4. Load price bars sorted by date to calculate trading-day windows
        logger.info("Loading price bars...")
        price_rows = safe_execute_query(
            session,
            """
            SELECT company_id, date, adj_close
            FROM price_bars
            WHERE interval = '1d'
            ORDER BY date ASC
            """
        )

        prices_by_company = {}
        for p in price_rows:
            prices_by_company.setdefault(p["company_id"], []).append((p["date"], p["adj_close"]))

        # Check existing backtest events to avoid duplicate processing
        existing_event_dates = {}
        existing_rows = safe_execute_query(
            session,
            "SELECT company_id, date FROM score_backtest_events"
        )
        for row in existing_rows:
            existing_event_dates.setdefault(row["company_id"], set()).add(row["date"])

        # Helper functions for fast lookups
        def _get_latest_value(sorted_list, key_name, target_date):
            best_val = None
            for item in sorted_list:
                if (item["as_of_date"] or date.min) <= target_date:
                    best_val = item[key_name]
                else:
                    break
            return best_val

        # Track the last recorded event date for each company (to implement 5-day spacing rule)
        # Load any existing ones from database first
        last_event_date_by_company = {}
        last_event_query = safe_execute_query(
            session,
            "SELECT company_id, MAX(date) AS max_date FROM score_backtest_events GROUP BY company_id"
        )
        for row in last_event_query:
            if row["max_date"]:
                last_event_date_by_company[row["company_id"]] = row["max_date"]

        events_to_insert = []
        all_dates = sorted(list(metrics_by_date.keys()))

        logger.info("Running backtest day-by-day...")
        for curr_date in all_dates:
            metrics = metrics_by_date[curr_date]

            for m in metrics:
                cid = m["company_id"]
                comp = company_map[cid]

                # Check if already processed
                if cid in existing_event_dates and curr_date in existing_event_dates[cid]:
                    continue

                # Check price bar index for 5 trading days spacing rule
                price_list = prices_by_company.get(cid, [])
                if not price_list:
                    continue

                date_to_idx = {p[0]: idx for idx, p in enumerate(price_list)}
                if curr_date not in date_to_idx:
                    continue

                curr_idx = date_to_idx[curr_date]

                # Apply the 5 trading days spacing constraint
                last_evt_date = last_event_date_by_company.get(cid)
                if last_evt_date and last_evt_date in date_to_idx:
                    last_idx = date_to_idx[last_evt_date]
                    if (curr_idx - last_idx) < 5:
                        continue

                # 5. Reconstruct ScoreInputs
                # Theme exposure
                theme_exp = _get_latest_value(cte_by_company.get(cid, []), "exposure_score", curr_date)

                # Recent news count (past 7 days)
                news_dates = news_by_company.get(cid, [])
                start_dt = datetime.combine(curr_date - timedelta(days=7), datetime.min.time())
                end_dt = datetime.combine(curr_date, datetime.max.time())
                news_count = sum(1 for dt in news_dates if start_dt <= dt <= end_dt)

                # Recent filing count (past 30 days)
                filing_dates = filing_by_company.get(cid, [])
                filing_count = sum(1 for d in filing_dates if curr_date - timedelta(days=30) <= d <= curr_date)

                # Upcoming earnings days
                earnings_dates = earnings_by_company.get(cid, [])
                upcoming_earnings = None
                for d in earnings_dates:
                    if d >= curr_date:
                        upcoming_earnings = (d - curr_date).days
                        break

                # Valuation flag
                val_flag = _get_latest_value(vps_by_company.get(cid, []), "valuation_flag", curr_date)

                # Revenue growth
                rev_growth = _get_latest_value(fs_by_company.get(cid, []), "revenue_growth", curr_date)

                # Build inputs dataclass
                inputs = ScoreInputs(
                    theme_exposure_score=theme_exp,
                    drawdown_52w=m["drawdown_52w"],
                    rsi_14=m["rsi_14"],
                    distance_from_200dma=m["distance_from_200dma"],
                    relative_return_vs_qqq_3m=m["relative_return_vs_qqq_3m"],
                    watch_status=watchlist_by_company.get(cid),
                    recent_news_count=news_count,
                    recent_filing_count=filing_count,
                    upcoming_earnings_days=upcoming_earnings,
                    return_1w=m["return_1w"],
                    macro_pressure_level=0, # Backtesting assumes neutral macro pressure for baseline
                    sector=comp["sector"],
                    valuation_flag=val_flag,
                    revenue_growth=rev_growth,
                )

                # Compute score
                breakdown = compute_opportunity_score(inputs)
                score = breakdown.opportunity_score

                # Calculate forward returns and drawdowns
                # 5D return
                ret_5d = None
                if curr_idx + 5 < len(price_list):
                    denom = price_list[curr_idx][1]
                    ret_5d = (price_list[curr_idx + 5][1] - denom) / denom if denom and denom > 0 else 0.0

                # 20D return & max drawdown
                ret_20d = None
                drawdown_20d = None
                if curr_idx + 20 < len(price_list):
                    denom = price_list[curr_idx][1]
                    ret_20d = (price_list[curr_idx + 20][1] - denom) / denom if denom and denom > 0 else 0.0
                    
                    # Calculate max drawdown over next 20 days
                    peak = price_list[curr_idx][1]
                    max_dd = 0.0
                    for i in range(1, 21):
                        p_val = price_list[curr_idx + i][1]
                        peak = max(peak, p_val)
                        dd = (p_val - peak) / peak if peak and peak > 0 else 0.0
                        max_dd = min(max_dd, dd)
                    drawdown_20d = max_dd

                # 60D return & max drawdown
                ret_60d = None
                drawdown_60d = None
                if curr_idx + 60 < len(price_list):
                    denom = price_list[curr_idx][1]
                    ret_60d = (price_list[curr_idx + 60][1] - denom) / denom if denom and denom > 0 else 0.0
                    
                    # Calculate max drawdown over next 60 days
                    peak = price_list[curr_idx][1]
                    max_dd = 0.0
                    for i in range(1, 61):
                        p_val = price_list[curr_idx + i][1]
                        peak = max(peak, p_val)
                        dd = (p_val - peak) / peak if peak and peak > 0 else 0.0
                        max_dd = min(max_dd, dd)
                    drawdown_60d = max_dd

                # Record event
                evt = ScoreBacktestEvent(
                    company_id=cid,
                    date=curr_date,
                    score=score,
                    indicators={
                        "theme_exposure_score": theme_exp,
                        "drawdown_52w": m["drawdown_52w"],
                        "rsi_14": m["rsi_14"],
                        "distance_from_200dma": m["distance_from_200dma"],
                        "relative_return_vs_qqq_3m": m["relative_return_vs_qqq_3m"],
                        "recent_news_count": news_count,
                        "recent_filing_count": filing_count,
                        "upcoming_earnings_days": upcoming_earnings,
                        "valuation_flag": val_flag,
                        "revenue_growth": rev_growth,
                    },
                    ret_5d=ret_5d,
                    ret_20d=ret_20d,
                    ret_60d=ret_60d,
                    drawdown_20d=drawdown_20d,
                    drawdown_60d=drawdown_60d,
                )
                session.add(evt)
                events_to_insert.append(evt)
                
                # Update spacing check state
                last_event_date_by_company[cid] = curr_date

        if events_to_insert:
            logger.info("Saving %s new backtest events...", len(events_to_insert))
            session.commit()
        else:
            logger.info("No new backtest events to save.")

        # 6. Re-aggregate statistics by score bucket and horizon
        logger.info("Re-aggregating backtest summaries...")
        # Clear existing summaries
        session.execute(text("DELETE FROM score_backtest_summaries"))
        session.commit()

        # Load all backtest events
        all_events = session.query(ScoreBacktestEvent).all()
        if not all_events:
            return {"events_created": len(events_to_insert)}

        # Map scores to buckets (e.g. 0-10, 10-20, ... 90-100)
        # Bucket ranges:
        # < 0: 'Below 0'
        # 0-10, 10-20, ... 90-100
        # > 100: 'Above 100'
        def _get_bucket(score_val):
            if score_val < 0:
                return "Below 0"
            if score_val >= 100:
                return "100+"
            lower = int(score_val // 10) * 10
            upper = lower + 10
            return f"{lower}-{upper}"

        events_data = []
        for e in all_events:
            events_data.append({
                "bucket": _get_bucket(e.score),
                "ret_5d": e.ret_5d,
                "ret_20d": e.ret_20d,
                "ret_60d": e.ret_60d,
                "dd_20d": e.drawdown_20d,
                "dd_60d": e.drawdown_60d,
            })

        df_ev = pd.DataFrame(events_data)
        summaries = []

        horizons = ["5d", "20d", "60d"]
        buckets = df_ev["bucket"].unique()

        for bucket in buckets:
            df_bucket = df_ev[df_ev["bucket"] == bucket]
            
            for horizon in horizons:
                # Get relevant returns/drawdowns
                if horizon == "5d":
                    rets = df_bucket["ret_5d"].dropna()
                    dds = pd.Series([0.0] * len(rets)) # Drawdown not tracked for 5D
                elif horizon == "20d":
                    rets = df_bucket["ret_20d"].dropna()
                    dds = df_bucket["dd_20d"].dropna()
                else:
                    rets = df_bucket["ret_60d"].dropna()
                    dds = df_bucket["dd_60d"].dropna()

                if rets.empty:
                    continue

                event_count = len(rets)
                hit_rate = sum(1 for r in rets if r > 0.0) / event_count
                avg_return = rets.mean()
                avg_drawdown = dds.mean() if not dds.empty else 0.0

                summary = ScoreBacktestSummary(
                    score_bucket=bucket,
                    horizon=horizon,
                    event_count=event_count,
                    hit_rate=hit_rate,
                    avg_return=avg_return,
                    avg_drawdown=avg_drawdown,
                )
                session.add(summary)
                summaries.append(summary)

        session.commit()
        logger.info("Saved %s backtest summaries.", len(summaries))

    return {"events_created": len(events_to_insert)}
