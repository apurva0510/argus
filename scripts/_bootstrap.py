import sys
from pathlib import Path

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from argus.core.logging import configure_logging  # noqa: E402

# Initialize application logging configuration
configure_logging()
