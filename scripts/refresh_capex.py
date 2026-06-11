try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.core.db import get_engine
from argus.core.migrations import run_migrations
from argus.pipelines.refresh_capex import refresh_capex


def main() -> None:
    run_migrations(get_engine())
    result = refresh_capex()
    print(
        "Capex refresh finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"error={result['error_text'] or 'none'}",
    )
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
