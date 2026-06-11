try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import sys
from argus.pipelines.refresh_filings import refresh_filings


def exit_code_for_status(status: str) -> int:
    return 1 if status == "failed" else 0


def main() -> None:
    print("Starting SEC filings refresh job...")
    result = refresh_filings()
    print("SEC filings refresh job completed.")
    print(f"Status: {result['status']}")
    print(f"Rows read: {result['rows_read']}")
    print(f"Rows written: {result['rows_written']}")
    if result.get("failed_symbols"):
        print(f"Failed symbols: {', '.join(result['failed_symbols'])}")
    if result.get("not_found_symbols"):
        print(f"SEC submission 404s: {', '.join(result['not_found_symbols'])}")
    if result.get("missing_cik_symbols"):
        print(f"Missing CIKs: {', '.join(result['missing_cik_symbols'])}")
    if result.get("identity_conflicts"):
        print(f"Identity conflicts: {', '.join(result['identity_conflicts'])}")
    if result.get("error_text"):
        print(f"Error: {result['error_text']}")
    if exit_code_for_status(str(result.get("status"))):
        sys.exit(1)


if __name__ == "__main__":
    main()
