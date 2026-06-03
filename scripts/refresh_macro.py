import argparse
import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh FRED macro indicators.")
    parser.add_argument(
        "--series",
        nargs="*",
        help="Optional FRED series codes to refresh. Defaults to the Argus macro set.",
    )
    return parser.parse_args()


def main() -> None:
    ensure_project_root_on_path()
    from argus.pipelines.refresh_macro import refresh_macro

    args = parse_args()
    result = refresh_macro(series_codes=args.series)
    print(result)
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
