try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from argus.core.init_db import main as init_db_main


def main() -> None:
    init_db_main()


if __name__ == "__main__":
    main()
