try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
from argus.pipelines.refresh_index import refresh_all_indexes, refresh_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh persisted Index Lab values.")
    parser.add_argument("--index-definition-id", type=int, default=None)
    parser.add_argument("--all-active", action="store_true")
    args = parser.parse_args()

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
