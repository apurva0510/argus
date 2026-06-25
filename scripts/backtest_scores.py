try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
from datetime import date, timedelta
import logging

from argus.pipelines.backtest_scores import backtest_opportunity_scores


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    
    default_start = (date.today() - timedelta(days=180)).isoformat()
    
    parser = argparse.ArgumentParser(description="Backtest opportunity scores and calculate forward return metrics.")
    parser.add_argument(
        "--start-date",
        type=str,
        default=default_start,
        help=f"The start date in YYYY-MM-DD format (default: {default_start})"
    )
    args = parser.parse_args()

    try:
        start_date = date.fromisoformat(args.start_date)
    except ValueError:
        print(f"Error: Invalid date format for --start-date: {args.start_date}. Must be YYYY-MM-DD.")
        return

    print(f"Starting opportunity score backtest from {start_date}...")
    result = backtest_opportunity_scores(start_date)
    print(f"Backtest finished. Created {result.get('events_created', 0)} new backtest events.")


if __name__ == "__main__":
    main()
