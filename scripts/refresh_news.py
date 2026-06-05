import sys
from pathlib import Path
import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Argus catalyst news from free sources.")
    parser.add_argument("--force", action="store_true", help="Bypass the recent successful refresh throttle.")
    parser.add_argument(
        "--bypass-refresh-throttle",
        action="store_true",
        help="Bypass only the recent successful refresh throttle while respecting provider cooldowns.",
    )
    parser.add_argument("--max-queries", type=int, default=None, help="Limit broad news queries for this run.")
    return parser.parse_args()


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.db import get_engine
    from argus.core.logging import configure_logging
    from argus.core.migrations import run_migrations
    from argus.pipelines.refresh_news import refresh_news

    args = parse_args()
    configure_logging()
    run_migrations(get_engine())
    print("Starting news refresh job (RSS & GDELT)...")
    result = refresh_news(
        force=args.force,
        bypass_recent_success=args.bypass_refresh_throttle,
        max_queries=args.max_queries,
    )
    print("News refresh job completed.")
    print(f"Status: {result['status']}")
    print(f"Rows read: {result['rows_read']}")
    print(f"Rows written: {result['rows_written']}")
    if result.get("failed_queries"):
        print(f"Failed queries: {', '.join(result['failed_queries'])}")
    if result.get("failed_providers"):
        print(f"Failed providers: {', '.join(result['failed_providers'])}")
    if result.get("error_text"):
        print(f"Warning: {result['error_text']}")


if __name__ == "__main__":
    main()
