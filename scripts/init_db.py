import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.init_db import main as init_db_main

    init_db_main()


if __name__ == "__main__":
    main()
