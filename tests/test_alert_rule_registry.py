from __future__ import annotations

import pytest

from argus.alerts.rule_registry import (
    ALERT_RULE_TYPES,
    build_rule_registry,
    validate_alert_config,
)
from argus.alerts.rules import RULE_CHECKERS, RULE_DEFINITIONS


def test_validate_alert_config_normalizes_supported_configs() -> None:
    assert validate_alert_config("price_below", {"threshold": "123.45"}) == {
        "threshold": 123.45
    }
    assert validate_alert_config("crossed_50dma", {"direction": " ABOVE "}) == {
        "direction": "above"
    }
    assert validate_alert_config("new_sec_filing", {"forms": "10-q"}) == {
        "forms": ["10-Q"]
    }
    assert validate_alert_config("news_keyword_match", {"keywords": "ai, power"}) == {
        "keywords": ["ai", "power"]
    }
    assert validate_alert_config("entered_pullback_zone", {}) == {
        "min_drawdown_pct": 10.0,
        "max_rsi": 55.0,
        "min_distance_from_200dma": -5.0,
    }


@pytest.mark.parametrize(
    ("rule_type", "config", "message"),
    [
        ("unknown", {}, "Unknown alert rule type"),
        ("price_above", {}, "threshold is required"),
        ("daily_move_gt", {"threshold_pct": "high"}, "threshold_pct must be numeric"),
        ("crossed_200dma", {"direction": "sideways"}, "direction must be one of"),
        ("new_sec_filing", {"forms": ["S-1"]}, "Unsupported SEC form"),
        ("earnings_within_days", {"days": 0}, "days must be at least 1"),
    ],
)
def test_validate_alert_config_rejects_invalid_configs(
    rule_type: str, config: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_alert_config(rule_type, config)


def test_rule_definitions_and_checkers_cannot_drift() -> None:
    assert set(RULE_CHECKERS) == ALERT_RULE_TYPES
    assert set(RULE_DEFINITIONS) == ALERT_RULE_TYPES
    for rule_type, definition in RULE_DEFINITIONS.items():
        assert definition.rule_type == rule_type
        assert definition.evaluator is RULE_CHECKERS[rule_type]
        assert definition.validate_config is not None


def test_build_rule_registry_requires_all_evaluators() -> None:
    incomplete = dict(RULE_CHECKERS)
    incomplete.pop("price_below")

    with pytest.raises(ValueError, match="Missing alert evaluator"):
        build_rule_registry(incomplete)
