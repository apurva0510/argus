try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import sys
from argus.pipelines.run_alerts import run_alerts


def main() -> None:
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
