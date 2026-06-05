import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.db import get_engine
    from argus.core.logging import configure_logging
    from argus.core.migrations import run_migrations
    from argus.pipelines.compute_signals import compute_signals

    configure_logging()
    run_migrations(get_engine())
    result = compute_signals()
    print(
        "Signal computation finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"error={result['error_text'] or 'none'}",
    )


if __name__ == "__main__":
    main()
