try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
from argus.pipelines.refresh_macro import refresh_macro


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh FRED macro indicators.")
    parser.add_argument(
        "--series",
        nargs="*",
        help="Optional FRED series codes to refresh. Defaults to the Argus macro set.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = refresh_macro(series_codes=args.series)
    print(result)
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
