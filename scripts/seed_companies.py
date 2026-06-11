try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.core.seed_companies import main as seed_companies_main


def main() -> None:
    seed_companies_main()


if __name__ == "__main__":
    main()
