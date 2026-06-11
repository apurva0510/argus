try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.core.db import get_engine
from argus.core.migrations import run_migrations
from argus.pipelines.compute_signals import compute_signals


def main() -> None:
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
