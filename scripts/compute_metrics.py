import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.logging import configure_logging
    from argus.pipelines.compute_metrics import compute_daily_metrics

    configure_logging()
    result = compute_daily_metrics()
    print(
        "Metrics computation finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"failed_symbols={','.join(result['failed_symbols']) or 'none'}",
    )


if __name__ == "__main__":
    main()
