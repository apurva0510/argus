import sys
from pathlib import Path


def ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> None:
    ensure_project_root_on_path()
    from argus.core.logging import configure_logging
    from argus.pipelines.run_alerts import run_alerts

    configure_logging()
    print("Running Argus alert check pipeline...")
    results = run_alerts()
    print("Results:")
    print(f"  Status:       {results['status']}")
    print(f"  Evaluations:  {results['rows_read']}")
    print(f"  Triggers:     {results['rows_written']}")
    if results["error_text"]:
        print(f"  Error:        {results['error_text']}")
        sys.exit(1)
    print("Alert pipeline finished successfully.")


if __name__ == "__main__":
    main()
