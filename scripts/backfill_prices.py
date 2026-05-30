import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill daily OHLCV prices from yfinance.")
    parser.add_argument("--period", default="2y", help="yfinance period (default: 2y)")
    return parser.parse_args()


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.logging import configure_logging
    from argus.pipelines.refresh_prices import refresh_prices

    args = parse_args()
    configure_logging()
    result = refresh_prices(period=args.period)
    print(
        "Price backfill finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"failed_symbols={','.join(result['failed_symbols']) or 'none'}",
    )


if __name__ == "__main__":
    main()
