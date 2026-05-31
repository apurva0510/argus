from argus.core import models  # noqa: F401
from argus.core.db import create_database_engine
from argus.core.settings import settings
from argus.core.migrations import run_migrations
from argus.core.settings import DATA_DIR


engine = None


def initialize_database() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "raw").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "lake").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
    # Create a real Engine instance for running migrations (do not rely on the
    # module-level proxy which may delay initialization). This ensures SQLAlchemy
    # inspection and Alembic-style migrations work correctly.
    database_engine = engine or create_database_engine(settings.database_url)
    run_migrations(database_engine)


def main() -> None:
    initialize_database()
    print("Database initialized.")


if __name__ == "__main__":
    main()
