try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.pipelines.compute_metrics import compute_daily_metrics


def main() -> None:
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
