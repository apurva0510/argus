try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
from argus.core.db import get_engine
from argus.core.migrations import run_migrations
from argus.pipelines.refresh_prices import refresh_prices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill OHLCV prices from yfinance.")
    parser.add_argument(
        "--period",
        default=None,
        help="yfinance period (default: 2y for daily, 5d for 15m)",
    )
    parser.add_argument(
        "--interval",
        default="1d",
        choices=("1d", "15m"),
        help="bar interval (default: 1d)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_migrations(get_engine())
    result = refresh_prices(period=args.period, interval=args.interval)
    print(
        "Price backfill finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"failed_symbols={','.join(result['failed_symbols']) or 'none'}",
    )


if __name__ == "__main__":
    main()
