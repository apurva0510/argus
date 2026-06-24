try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.pipelines.refresh_fundamentals import refresh_fundamentals


def main() -> None:
    result = refresh_fundamentals()
    print(result)
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
