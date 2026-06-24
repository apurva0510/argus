from __future__ import annotations

from datetime import date

from sqlalchemy import text

from argus.analytics.valuation import build_peer_rows, compute_ev_sales_to_growth
from argus.core.db import get_insert_statement_producer, session_scope
from argus.core.models import ValuationPeerSnapshot
from argus.pipelines.job_runs import job_run_context


def _load_latest_fundamentals(session) -> list[dict]:
    rows = session.execute(
        text(
            """
            SELECT
                fs.company_id,
                fs.as_of_date,
                fs.forward_pe,
                fs.trailing_pe,
                fs.price_to_sales,
                fs.ev_to_sales,
                fs.ev_to_ebitda,
                fs.revenue_growth
            FROM fundamentals_snapshot fs
            JOIN companies c ON c.id = fs.company_id
            WHERE c.is_active = TRUE
                AND fs.id = (
                    SELECT fs2.id
                    FROM fundamentals_snapshot fs2
                    WHERE fs2.company_id = fs.company_id
                    ORDER BY fs2.as_of_date DESC, fs2.created_at DESC, fs2.id DESC
                    LIMIT 1
                )
            """
        )
    ).mappings()
    fundamentals: list[dict] = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("as_of_date"), str):
            item["as_of_date"] = date.fromisoformat(item["as_of_date"])
        item["ev_sales_to_growth"] = compute_ev_sales_to_growth(
            item.get("ev_to_sales"),
            item.get("revenue_growth"),
        )
        fundamentals.append(item)
    return fundamentals


def _load_peer_memberships(session) -> list[dict]:
    sector_rows = session.execute(
        text(
            """
            SELECT
                c.id AS company_id,
                'sector' AS peer_group_type,
                c.sector AS peer_group_key
            FROM companies c
            WHERE c.is_active = TRUE
                AND c.sector IS NOT NULL
                AND c.sector != ''
            """
        )
    ).mappings()

    theme_rows = session.execute(
        text(
            """
            SELECT
                c.id AS company_id,
                'theme' AS peer_group_type,
                t.code AS peer_group_key
            FROM companies c
            JOIN company_theme_exposure cte ON cte.company_id = c.id
            JOIN themes t ON t.id = cte.theme_id
            WHERE c.is_active = TRUE
                AND cte.id = (
                    SELECT cte2.id
                    FROM company_theme_exposure cte2
                    WHERE cte2.company_id = c.id
                    ORDER BY cte2.exposure_score DESC, cte2.id ASC
                    LIMIT 1
                )
            """
        )
    ).mappings()

    return [dict(row) for row in sector_rows] + [dict(row) for row in theme_rows]


def _upsert_peer_snapshot(session, row: dict) -> int:
    insert_fn = get_insert_statement_producer(session)
    statement = insert_fn(ValuationPeerSnapshot).values(row)
    statement = statement.on_conflict_do_update(
        index_elements=[
            "company_id",
            "as_of_date",
            "peer_group_type",
            "peer_group_key",
            "metric_name",
        ],
        set_={
            "company_value": statement.excluded.company_value,
            "peer_median": statement.excluded.peer_median,
            "peer_count": statement.excluded.peer_count,
            "percentile_rank": statement.excluded.percentile_rank,
            "premium_discount_pct": statement.excluded.premium_discount_pct,
            "valuation_flag": statement.excluded.valuation_flag,
        },
    )
    session.execute(statement)
    return 1


def compute_valuation_peers() -> dict[str, object]:
    with job_run_context("compute_valuation_peers") as state:
        with session_scope() as session:
            fundamentals = _load_latest_fundamentals(session)
            memberships = _load_peer_memberships(session)
            peer_rows = build_peer_rows(fundamentals, memberships)
            state.rows_read = len(fundamentals)

            for peer_row in peer_rows:
                state.rows_written += _upsert_peer_snapshot(
                    session,
                    {
                        "company_id": peer_row.company_id,
                        "as_of_date": peer_row.as_of_date,
                        "peer_group_type": peer_row.peer_group_type,
                        "peer_group_key": peer_row.peer_group_key,
                        "metric_name": peer_row.metric_name,
                        "company_value": peer_row.company_value,
                        "peer_median": peer_row.peer_median,
                        "peer_count": peer_row.peer_count,
                        "percentile_rank": peer_row.percentile_rank,
                        "premium_discount_pct": peer_row.premium_discount_pct,
                        "valuation_flag": peer_row.valuation_flag,
                    },
                )

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "error_text": state.error_text,
    }
