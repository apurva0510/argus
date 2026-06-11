from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

AlertEvaluator = Callable[..., list[dict] | None]
ConfigValidator = Callable[[dict], dict | None]

ALERT_DIRECTIONS = {"any", "above", "below"}
ALERT_FORM_TYPES = {"10-K", "10-Q", "8-K", "6-K", "20-F", "40-F"}


@dataclass(frozen=True)
class AlertRuleDefinition:
    rule_type: str
    validate_config: ConfigValidator
    evaluator: AlertEvaluator | None = None

    def with_evaluator(self, evaluator: AlertEvaluator) -> AlertRuleDefinition:
        return AlertRuleDefinition(
            rule_type=self.rule_type,
            validate_config=self.validate_config,
            evaluator=evaluator,
        )


def _threshold_config(config: dict) -> dict:
    return {"threshold": _required_float(config, "threshold")}


def _threshold_pct_config(config: dict) -> dict:
    return {"threshold_pct": _required_float(config, "threshold_pct")}


def _moving_average_cross_config(config: dict) -> dict:
    direction = str(config.get("direction", "any")).strip().lower()
    if direction not in ALERT_DIRECTIONS:
        raise ValueError("direction must be one of: any, above, below")
    return {"direction": direction}


def _sec_filing_config(config: dict) -> dict | None:
    forms = config.get("forms")
    if not forms:
        return None
    if isinstance(forms, str):
        forms = [forms]
    cleaned_forms = [str(form).strip().upper() for form in forms if str(form).strip()]
    invalid_forms = [form for form in cleaned_forms if form not in ALERT_FORM_TYPES]
    if invalid_forms:
        raise ValueError(f"Unsupported SEC form type(s): {', '.join(invalid_forms)}")
    return {"forms": cleaned_forms} if cleaned_forms else None


def _news_keyword_config(config: dict) -> dict | None:
    keywords = config.get("keywords")
    if keywords is None:
        return None
    if isinstance(keywords, str):
        cleaned_keywords = [kw.strip() for kw in keywords.split(",") if kw.strip()]
    else:
        cleaned_keywords = [str(kw).strip() for kw in keywords if str(kw).strip()]
    return {"keywords": cleaned_keywords} if cleaned_keywords else None


def _earnings_within_days_config(config: dict) -> dict:
    days = int(_required_float(config, "days"))
    if days < 1:
        raise ValueError("days must be at least 1")
    return {"days": days}


def _pullback_zone_config(config: dict) -> dict:
    return {
        "min_drawdown_pct": _optional_float(config, "min_drawdown_pct", 10.0),
        "max_rsi": _optional_float(config, "max_rsi", 55.0),
        "min_distance_from_200dma": _optional_float(config, "min_distance_from_200dma", -5.0),
    }


RULE_CONFIG_VALIDATORS: dict[str, ConfigValidator] = {
    "price_below": _threshold_config,
    "price_above": _threshold_config,
    "daily_move_gt": _threshold_pct_config,
    "drawdown_52w_gt": _threshold_pct_config,
    "rsi_below": _threshold_config,
    "crossed_50dma": _moving_average_cross_config,
    "crossed_200dma": _moving_average_cross_config,
    "new_sec_filing": _sec_filing_config,
    "news_keyword_match": _news_keyword_config,
    "earnings_within_days": _earnings_within_days_config,
    "entered_pullback_zone": _pullback_zone_config,
}
ALERT_RULE_TYPES = frozenset(RULE_CONFIG_VALIDATORS)


def build_rule_registry(
    evaluators: dict[str, AlertEvaluator],
) -> dict[str, AlertRuleDefinition]:
    missing = ALERT_RULE_TYPES - set(evaluators)
    if missing:
        raise ValueError(f"Missing alert evaluator(s): {', '.join(sorted(missing))}")

    return {
        rule_type: AlertRuleDefinition(
            rule_type=rule_type,
            validate_config=validator,
            evaluator=evaluators[rule_type],
        )
        for rule_type, validator in RULE_CONFIG_VALIDATORS.items()
    }


def validate_alert_config(rule_type: str, config_json: dict | None) -> dict | None:
    validator = RULE_CONFIG_VALIDATORS.get(rule_type)
    if validator is None:
        raise ValueError(f"Unknown alert rule type: {rule_type}")
    return validator(config_json or {})


def _required_float(config: dict, key: str) -> float:
    if key not in config or config[key] is None:
        raise ValueError(f"{key} is required")
    return _coerce_float(config[key], key)


def _optional_float(config: dict, key: str, default: float) -> float:
    value = config.get(key, default)
    return _coerce_float(value, key)


def _coerce_float(value: Any, key: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
