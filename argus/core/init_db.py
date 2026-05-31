from argus.core import models  # noqa: F401
from argus.core.db import engine
from argus.core.migrations import run_migrations
from argus.core.settings import DATA_DIR


def initialize_database() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "raw").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "lake").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
    run_migrations(engine)


def main() -> None:
    initialize_database()
    print("Database initialized.")


if __name__ == "__main__":
    main()
