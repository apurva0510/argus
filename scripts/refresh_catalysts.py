try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import logging

from argus.pipelines.refresh_catalysts import refresh_catalyst_impact


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    
    print("Starting catalyst impact ingestion pipeline...")
    result = refresh_catalyst_impact()
    print(
        "Catalyst impact ingestion finished.",
        f"events_created={result.get('events_created', 0)}",
        f"snapshots_updated={result.get('snapshots_updated', 0)}"
    )


if __name__ == "__main__":
    main()
