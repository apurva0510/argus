try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import sys
from argus.pipelines.refresh_ciks import refresh_ciks


def exit_code_for_status(status: str) -> int:
    return 1 if status == "failed" else 0


def main() -> None:
    result = refresh_ciks()
    print(
        "CIK refresh finished. "
        f"status={result['status']} rows_read={result['rows_read']} "
        f"rows_written={result['rows_written']}"
    )
    if result.get("updated_symbols"):
        print(f"Updated symbols: {', '.join(result['updated_symbols'])}")
    if result.get("missing_symbols"):
        print(f"Unmatched symbols: {', '.join(result['missing_symbols'])}")
    if result.get("identity_conflicts"):
        print(f"Identity conflicts: {', '.join(result['identity_conflicts'])}")
    if result.get("error_text"):
        print(f"Details: {result['error_text']}")
    if exit_code_for_status(str(result.get("status"))):
        sys.exit(1)


if __name__ == "__main__":
    main()
