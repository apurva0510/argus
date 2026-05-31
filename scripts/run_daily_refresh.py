import argparse
import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Argus daily refresh workflow.")
    parser.add_argument("--period", default="2y", help="yfinance period for price refresh")
    parser.add_argument("--skip-news", action="store_true", help="Skip RSS/GDELT news refresh")
    parser.add_argument("--skip-filings", action="store_true", help="Skip SEC filings refresh")
    parser.add_argument("--skip-alerts", action="store_true", help="Skip alert evaluation")
    return parser.parse_args()


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.db import get_engine
    from argus.core.logging import configure_logging
    from argus.core.migrations import run_migrations
    from argus.pipelines.run_daily_refresh import run_daily_refresh

    args = parse_args()
    configure_logging()
    run_migrations(get_engine())
    result = run_daily_refresh(
        period=args.period,
        include_news=not args.skip_news,
        include_filings=not args.skip_filings,
        include_alerts=not args.skip_alerts,
    )

    print("Daily refresh finished.")
    print(f"Status: {result['status']}")
    print(f"Rows read: {result['rows_read']}")
    print(f"Rows written: {result['rows_written']}")
    for step_name, step_result in result["results"].items():
        print(f"- {step_name}: {step_result.get('status', 'unknown')}")
    if result.get("error_text"):
        print(f"Error: {result['error_text']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
