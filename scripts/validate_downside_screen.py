"""Rolling, read-only validation of a selective 20-session downside screen."""

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.tree import DecisionTreeClassifier

from argus.analytics.predictive_signals import load_history
from argus.analytics.downside_screen import DOWNSIDE_VOLATILITY_MAX
from argus.analytics.pullback_outcomes import FEATURES, build_pullback_events
from argus.core.db import get_engine
from scripts.experiment_pullback_recovery import selection_report


def choose_early_cutoff(train):
    """Largest simple threshold with >=70% avoidance and >=5pp lift in early data."""
    safe = 1 - train["breakdown"]
    baseline = float(safe.mean())
    eligible = []
    for threshold in (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        report = selection_report(safe, train["volatility_20d"] <= threshold, train)
        if (report["passes_gate"] and report["hit_rate"] >= baseline + 0.05):
            eligible.append(threshold)
    return max(eligible) if eligible else None


def expanding_folds(events, count=3, first_train_fraction=0.45):
    dates = np.array(sorted(events["date"].unique()))
    if len(dates) < 120:
        raise ValueError("Too few event dates")
    boundaries = np.linspace(int(len(dates) * first_train_fraction), len(dates), count + 1,
                             dtype=int)
    for i in range(count):
        start, end = dates[boundaries[i]], dates[boundaries[i + 1] - 1]
        train = events.loc[events["exit_date"] < start]
        test = events.loc[(events["date"] >= start) & (events["date"] <= end)]
        if train.empty or test.empty:
            raise ValueError("Empty chronological fold")
        yield train, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--first-train-fraction", type=float, default=0.45)
    args = parser.parse_args()
    with get_engine().connect() as connection:
        bars, metrics = load_history(connection)
    events = build_pullback_events(bars, metrics, horizon=20, spacing=20,
                                   pullback_only=False, breakdown_threshold=-0.10)
    report = {"target": "avoid a 10% closing loss within 20 sessions after next-open entry",
              "events": len(events), "folds": []}
    first_train, _ = next(expanding_folds(
        events, count=args.folds, first_train_fraction=args.first_train_fraction
    ))
    report["early_training_cutoff"] = choose_early_cutoff(first_train)
    report["deployed_cutoff"] = DOWNSIDE_VOLATILITY_MAX
    for number, (train, test) in enumerate(expanding_folds(
        events, count=args.folds, first_train_fraction=args.first_train_fraction
    ), 1):
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            DecisionTreeClassifier(max_depth=3, min_samples_leaf=30, random_state=42),
        )
        model.fit(train[list(FEATURES)], train["breakdown"])
        train_risk = model.predict_proba(train[list(FEATURES)])[:, 1]
        risk = model.predict_proba(test[list(FEATURES)])[:, 1]
        safe = 1 - test["breakdown"]
        model_selection = selection_report(safe, risk <= 0.25, test)
        simple_selection = selection_report(safe, test["volatility_20d"] <= 0.30, test)
        fixed_selection = selection_report(
            safe, test["volatility_20d"] <= DOWNSIDE_VOLATILITY_MAX, test
        )
        matched_cutoff = float(np.quantile(
            train["volatility_20d"], np.mean(train_risk <= 0.25)
        ))
        matched_volatility = selection_report(
            safe, test["volatility_20d"] <= matched_cutoff, test
        )
        report["folds"].append({
            "fold": number,
            "train_end": str(train["date"].max().date()),
            "test_start": str(test["date"].min().date()),
            "test_end": str(test["date"].max().date()),
            "test_events": len(test),
            "no_screen": selection_report(safe, np.ones(len(test), dtype=bool), test),
            "tree_risk_at_most_25pct": model_selection,
            "simple_volatility_at_most_30pct": simple_selection,
            "fixed_volatility_at_most_35pct": fixed_selection,
            "matched_coverage_volatility_cutoff": round(matched_cutoff, 3),
            "matched_coverage_volatility": matched_volatility,
        })
    report["promotion_gate"] = {
        "fixed_rule_all_folds_pass": all(
            fold["fixed_volatility_at_most_35pct"]["passes_gate"]
            for fold in report["folds"]
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
