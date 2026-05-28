from ai_infra_watcher.core.seed import SECTOR_GROUPS


def test_seed_universe_has_benchmarks() -> None:
    assert "AI Capex Benchmarks" in SECTOR_GROUPS
    assert "NVDA" in SECTOR_GROUPS["AI Capex Benchmarks"]
