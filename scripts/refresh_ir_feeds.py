try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
from argus.core.db import get_engine
from argus.core.migrations import run_migrations
from argus.pipelines.refresh_ir_feeds import refresh_ir_feeds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Argus investor relations news feeds.")
    parser.add_argument(
        "--force", action="store_true", help="Bypass the recent successful refresh throttle."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_migrations(get_engine())
    print("Starting IR feed refresh job...")
    result = refresh_ir_feeds(force=args.force)
    print("IR feed refresh job completed.")
    print(f"Status: {result['status']}")
    print(f"Rows read: {result['rows_read']}")
    print(f"Rows written: {result['rows_written']}")
    if result.get("error_text"):
        print(f"Warning: {result['error_text']}")


if __name__ == "__main__":
    main()
