try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.pipelines.compute_scores import compute_opportunity_scores


def main() -> None:
    result = compute_opportunity_scores()
    print(
        "Opportunity score computation finished.",
        f"status={result['status']}",
        f"rows_read={result['rows_read']}",
        f"rows_written={result['rows_written']}",
        f"error={result['error_text'] or 'none'}",
    )


if __name__ == "__main__":
    main()
