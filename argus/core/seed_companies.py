from argus.core.db import session_scope
from argus.core.seed import (
    seed_companies,
    seed_exposure_defaults,
    seed_themes,
    seed_watchlists,
)


def seed_database() -> None:
    with session_scope() as session:
        seed_themes(session)
        session.flush()
        seed_companies(session)
        session.flush()
        seed_watchlists(session)
        seed_exposure_defaults(session)


def main() -> None:
    seed_database()
    print("Seed data loaded.")


if __name__ == "__main__":
    main()
