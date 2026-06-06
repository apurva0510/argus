import sys
from pathlib import Path
import argparse


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh persisted Index Lab values.")
    parser.add_argument("--index-definition-id", type=int, default=None)
    parser.add_argument("--all-active", action="store_true")
    args = parser.parse_args()

    ensure_project_root_on_path()
    from argus.core.logging import configure_logging
    from argus.pipelines.refresh_index import refresh_all_indexes, refresh_index

    configure_logging()
    if args.all_active:
        result = refresh_all_indexes()
    else:
        result = refresh_index(index_definition_id=args.index_definition_id)
    print(
        "Index refresh finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"error={result['error_text'] or 'none'}",
    )


if __name__ == "__main__":
    main()
