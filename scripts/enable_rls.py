"""Enable Row Level Security (RLS) on all Argus tables in Supabase.

Supabase exposes the 'public' schema via PostgREST. Without RLS, anyone
with the anon key can read/write data.  This script:

1. Enables RLS on every Argus table.
2. Creates a permissive policy allowing full access for the 'postgres' role
   (used by the DATABASE_URL connection string).
3. PostgREST anonymous access is effectively blocked since no policy grants
   access to the 'anon' or 'authenticated' roles.

Safe to run multiple times (idempotent via IF NOT EXISTS / OR REPLACE).

Usage:
    DATABASE_URL="postgresql://..." python scripts/enable_rls.py
"""

import os
import sys

from sqlalchemy import create_engine, text

TABLES = [
    "themes",
    "job_runs",
    "app_settings",
    "companies",
    "company_theme_exposure",
    "watchlists",
    "watchlist_items",
    "price_bars",
    "daily_metrics",
    "fundamentals_snapshot",
    "news_items",
    "news_mentions",
    "sec_filings",
    "earnings_events",
    "alerts",
    "user_notes",
    "alert_events",
    "provider_health",
    "index_values",
]


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url or database_url.startswith("sqlite"):
        print("ERROR: This script requires a PostgreSQL DATABASE_URL.")
        print("Usage: DATABASE_URL='postgresql://...' python scripts/enable_rls.py")
        sys.exit(1)

    # Normalize for SQLAlchemy + psycopg v3
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(
        database_url,
        future=True,
        connect_args={"prepare_threshold": None},
    )

    with engine.connect() as conn:
        db_role = conn.execute(text("SELECT current_user")).scalar_one()
        quoted_role = _quote_identifier(db_role)
        for table in TABLES:
            conn.execute(text(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS argus_full_access ON public.{table}"))
            conn.execute(
                text(
                    f"CREATE POLICY argus_full_access ON public.{table} "
                    f"FOR ALL TO {quoted_role} USING (true) WITH CHECK (true)"
                )
            )
            print(f"  ✓ {table}: RLS enabled, {db_role} policy created")

        conn.commit()

    engine.dispose()
    print("\nDone — RLS enabled on all tables.")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


if __name__ == "__main__":
    main()
