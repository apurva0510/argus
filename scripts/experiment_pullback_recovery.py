"""Read-only next-open evaluation of healthy pullback recovery versus breakdown."""

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from argus.analytics.predictive_signals import load_history
from argus.analytics.pullback_outcomes import FEATURES, build_pullback_events
from argus.core.db import get_engine

MINIMUM_HIT_RATE = 0.70
MINIMUM_SIGNALS = 30
MINIMUM_COMPANIES = 10
MINIMUM_DATES = 20


def chronological_event_split(events, test_fraction=0.30):
    dates = sorted(events["date"].unique())
    if len(dates) < 20:
        raise ValueError("Too few distinct event dates")
    first_test = dates[int(len(dates) * (1 - test_fraction))]
    train = events.loc[events["exit_date"] < first_test].copy()
    test = events.loc[events["date"] >= first_test].copy()
    if train.empty or test.empty:
        raise ValueError("No train or test events after label embargo")
    return train, test


def selection_report(labels, mask, events=None):
    count = int(mask.sum())
    companies = int(events.loc[mask, "company_id"].nunique()) if events is not None else None
    dates = int(events.loc[mask, "date"].nunique()) if events is not None else None
    return {
        "signals": count,
        "coverage": round(count / len(labels), 3),
        "companies": companies,
        "dates": dates,
        "hit_rate": round(float(labels[mask].mean()), 3) if count else None,
        "setup_hit_rate": round(float(labels.mean()), 3),
        "passes_gate": bool(
            count >= MINIMUM_SIGNALS
            and (companies is None or companies >= MINIMUM_COMPANIES)
            and (dates is None or dates >= MINIMUM_DATES)
            and labels[mask].mean() >= MINIMUM_HIT_RATE
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-fraction", type=float, default=0.30)
    parser.add_argument("--target", choices=("healthy_recovery", "breakdown"),
                        default="healthy_recovery")
    args = parser.parse_args()
    with get_engine().connect() as connection:
        bars, metrics = load_history(connection)
    events = build_pullback_events(bars, metrics)
    train, test = chronological_event_split(events, args.test_fraction)
    x_train, x_test = train[list(FEATURES)], test[list(FEATURES)]
    y_train, y_test = train[args.target], test[args.target]
    output = {
        "definition": "10-25% drawdown, above 200DMA; next-open entry; after 60 sessions beats QQQ by >=5pp without a 15% closing loss",
        "target": args.target,
        "events": len(events), "companies": int(events["company_id"].nunique()),
        "train_events": len(train), "test_events": len(test),
        "test_start": str(test["date"].min().date()),
        "test_end": str(test["date"].max().date()),
        "train_target_rate": round(float(y_train.mean()), 3),
        "test_target_rate": round(float(y_test.mean()), 3),
        "test_breakdown_rate": round(float(test["breakdown"].mean()), 3),
        "minimum_hit_rate": MINIMUM_HIT_RATE,
        "minimum_test_signals": MINIMUM_SIGNALS,
        "minimum_companies": MINIMUM_COMPANIES,
        "minimum_dates": MINIMUM_DATES,
        "comparisons": {},
    }
    # This fixed rule is a simple comparator, not a tuned feature search.
    if args.target == "healthy_recovery":
        rule = (test["relative_return_vs_qqq_3m"] > 0) & test["rsi_14"].between(35, 50)
    else:
        rule = (test["relative_return_vs_qqq_3m"] < 0) & (test["rsi_14"] < 40)
    output["comparisons"]["fixed_rule"] = selection_report(y_test, rule, test)
    models = {
        "logistic": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                  LogisticRegression(max_iter=1000)),
        "shallow_tree": make_pipeline(SimpleImputer(strategy="median"),
                                      DecisionTreeClassifier(max_depth=2,
                                                             min_samples_leaf=12,
                                                             random_state=42)),
    }
    for name, model in models.items():
        model.fit(x_train, y_train)
        probabilities = model.predict_proba(x_test)[:, 1]
        selected = probabilities >= 0.70
        output["comparisons"][name] = {
            "auc": round(float(roc_auc_score(y_test, probabilities)), 3)
            if y_test.nunique() == 2 else None,
            "brier": round(float(brier_score_loss(y_test, probabilities)), 3),
            "predicted_70pct_or_more": selection_report(y_test, selected, test),
            "highest_fifth": selection_report(
                y_test, probabilities >= np.quantile(probabilities, 0.8), test
            ),
        }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
