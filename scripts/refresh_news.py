import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.logging import configure_logging
    from argus.pipelines.refresh_news import refresh_news

    configure_logging()
    print("Starting news refresh job (RSS & GDELT)...")
    result = refresh_news()
    print("News refresh job completed.")
    print(f"Status: {result['status']}")
    print(f"Rows read: {result['rows_read']}")
    print(f"Rows written: {result['rows_written']}")
    if result.get("failed_symbols"):
        print(f"Failed symbols: {', '.join(result['failed_symbols'])}")
    if result.get("error_text"):
        print(f"Error: {result['error_text']}")


if __name__ == "__main__":
    main()
