import argparse
import sys
from datetime import date
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add or update a manual quarterly capex observation."
    )
    parser.add_argument("--ticker", required=True, help="Company ticker, e.g. MSFT")
    parser.add_argument("--period-end", required=True, help="Fiscal period end date, YYYY-MM-DD")
    parser.add_argument("--capex", required=True, type=float, help="Capex amount in currency units")
    parser.add_argument("--currency", default="USD", help="Currency code, default USD")
    parser.add_argument("--source-label", default=None, help="Source label, e.g. Q1 earnings")
    parser.add_argument("--source-url", default=None, help="Optional source URL")
    parser.add_argument("--notes", default=None, help="Optional notes")
    return parser.parse_args()


def main() -> None:
    ensure_project_root_on_path()
    from argus.pipelines.capex_observations import upsert_capex_observation

    args = parse_args()
    result = upsert_capex_observation(
        ticker=args.ticker,
        fiscal_period_end=date.fromisoformat(args.period_end),
        capex_amount=args.capex,
        currency=args.currency,
        source_label=args.source_label,
        source_url=args.source_url,
        notes=args.notes,
    )
    print(result)


if __name__ == "__main__":
    main()
