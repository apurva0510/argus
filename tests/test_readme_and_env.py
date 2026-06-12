import re
from pathlib import Path
import subprocess
import sys


def test_package_import_from_install():
    """Verify that all core components can be imported from the argus package."""
    import argus
    import argus.core.settings
    import argus.core.models
    import argus.core.db
    import argus.pipelines.refresh_prices
    import argus.services.dashboard_service

    assert argus is not None


def test_settings_field_defaults_no_secrets():
    """Verify that Settings defines secure, blank, or local-friendly defaults without requiring secrets."""
    from argus.core.settings import Settings

    fields = Settings.model_fields

    assert fields["app_password"].default == ""
    assert fields["finnhub_api_key"].default == ""
    assert fields["twelve_data_api_key"].default == ""
    assert fields["alpha_vantage_api_key"].default == ""
    assert fields["market_data_provider"].default == "yfinance"


def test_env_example_matches_settings():
    """Verify that every variable defined in .env.example matches a configured Pydantic setting field."""
    from argus.core.settings import Settings

    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    assert env_example_path.exists(), ".env.example is missing in root directory"

    env_keys = set()
    key_pattern = re.compile(r"^([A-Z0-9_]+)=")

    with open(env_example_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = key_pattern.match(line)
            if match:
                env_keys.add(match.group(1))

    settings_fields = set()
    for field_name, field_info in Settings.model_fields.items():
        alias = field_info.alias or field_name
        settings_fields.add(alias)

    missing_in_env = settings_fields - env_keys
    assert not missing_in_env, f"Settings fields not documented in .env.example: {missing_in_env}"


def test_readme_script_commands_exist():
    """Extract script commands from README.md and verify the referenced python files exist in the codebase."""
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    assert readme_path.exists(), "README.md is missing in root directory"

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    project_root = Path(__file__).resolve().parents[1]

    # 1. Parse and check python script executions e.g. python scripts/init_db.py
    script_pattern = re.compile(r"python3?\s+(scripts/[a-zA-Z0-9_\-]+\.py)")
    script_matches = script_pattern.findall(content)

    for script_rel_path in script_matches:
        script_abs_path = project_root / script_rel_path
        assert script_abs_path.exists(), (
            f"README references non-existent python script: {script_rel_path}"
        )

    # 2. Parse and check streamlit entrypoint e.g. streamlit run app/main.py
    app_pattern = re.compile(r"streamlit\s+run\s+(app/[a-zA-Z0-9_\-/]+\.py)")
    app_matches = app_pattern.findall(content)

    for app_rel_path in app_matches:
        app_abs_path = project_root / app_rel_path
        assert app_abs_path.exists(), (
            f"README references non-existent app entrypoint: {app_rel_path}"
        )


def test_script_bootstrap_imports_from_non_repo_cwd(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "_bootstrap.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
