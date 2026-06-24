try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.pipelines.compute_valuation_peers import compute_valuation_peers


def main() -> None:
    result = compute_valuation_peers()
    print(result)


if __name__ == "__main__":
    main()
