"""Read-only experiment for a 10% closing decline in the next 20 sessions."""

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from argus.analytics.predictive_signals import load_history
from argus.analytics.pullback_outcomes import FEATURES, build_pullback_events
from argus.core.db import get_engine
from scripts.experiment_pullback_recovery import chronological_event_split, selection_report


def main():
    with get_engine().connect() as connection:
        bars, metrics = load_history(connection)
    events = build_pullback_events(bars, metrics, horizon=20, spacing=20,
                                   pullback_only=False, breakdown_threshold=-0.10)
    train, test = chronological_event_split(events, test_fraction=0.25)
    x_train, x_test = train[list(FEATURES)], test[list(FEATURES)]
    y_train, y_test = train["breakdown"], test["breakdown"]
    output = {
        "target": "next-open entry followed by a 10% closing loss within 20 sessions",
        "events": len(events), "companies": int(events["company_id"].nunique()),
        "train_events": len(train), "test_events": len(test),
        "test_start": str(test["date"].min().date()),
        "test_end": str(test["date"].max().date()),
        "train_event_rate": round(float(y_train.mean()), 3),
        "test_event_rate": round(float(y_test.mean()), 3),
        "models": {},
    }
    models = {
        "logistic": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                  LogisticRegression(max_iter=1000)),
        "shallow_tree": make_pipeline(SimpleImputer(strategy="median"),
                                      DecisionTreeClassifier(max_depth=3,
                                                             min_samples_leaf=30,
                                                             random_state=42)),
        "random_forest": make_pipeline(SimpleImputer(strategy="median"),
                                       RandomForestClassifier(n_estimators=150,
                                                              max_depth=4,
                                                              min_samples_leaf=30,
                                                              random_state=42,
                                                              n_jobs=1)),
    }
    for name, model in models.items():
        model.fit(x_train, y_train)
        probabilities = model.predict_proba(x_test)[:, 1]
        output["models"][name] = {
            "auc": round(float(roc_auc_score(y_test, probabilities)), 3),
            "brier": round(float(brier_score_loss(y_test, probabilities)), 3),
            "base_brier": round(float(brier_score_loss(
                y_test, np.full(len(test), y_train.mean()))), 3),
            "predicted_70pct_or_more": selection_report(y_test, probabilities >= 0.7, test),
            "highest_tenth": selection_report(
                y_test, probabilities >= np.quantile(probabilities, 0.9), test),
            "lowest_quarter_no_breakdown": selection_report(
                1 - y_test, probabilities <= np.quantile(probabilities, 0.25), test),
        }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
