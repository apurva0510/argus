import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def exit_code_for_status(status: str) -> int:
    return 1 if status == "failed" else 0


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.logging import configure_logging
    from argus.pipelines.refresh_ciks import refresh_ciks

    configure_logging()
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
