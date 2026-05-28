import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_infra_watcher.core.db import session_scope
from ai_infra_watcher.core.seed import (
    seed_companies,
    seed_exposure_defaults,
    seed_themes,
    seed_watchlists,
)


def main() -> None:
    with session_scope() as session:
        seed_themes(session)
        session.flush()
        seed_companies(session)
        session.flush()
        seed_watchlists(session)
        seed_exposure_defaults(session)
    print("Seed data loaded.")


if __name__ == "__main__":
    main()
