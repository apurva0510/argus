"""Read-only comparison of technical tree models against simple baselines."""

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.tree import DecisionTreeClassifier

from argus.analytics.predictive_signals import FEATURES, build_dataset, chronological_split, load_history
from argus.core.db import get_engine


def evaluate(y, probabilities, excess_returns):
    cutoff = np.quantile(probabilities, 0.8)
    selected = probabilities >= cutoff
    return {
        "auc": round(float(roc_auc_score(y, probabilities)), 3),
        "brier": round(float(brier_score_loss(y, probabilities)), 3),
        "top_quintile_hit_rate": round(float(np.mean(y[selected])), 3),
        "top_quintile_mean_excess_return": round(float(np.mean(excess_returns[selected])), 4),
        "selected_rows": int(selected.sum()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    args = parser.parse_args()
    with get_engine().connect() as connection:
        bars, metrics = load_history(connection)
    data = build_dataset(bars, metrics)
    train, test = chronological_split(data, args.test_fraction)
    x_train, x_test = train[list(FEATURES)], test[list(FEATURES)]
    y_train, y_test = train["outperformed_qqq"], test["outperformed_qqq"]
    results = {
        "target": "20-session close-to-close excess return versus QQQ > 0",
        "train_rows": len(train), "test_rows": len(test),
        "train_dates": [str(train["date"].min().date()), str(train["date"].max().date())],
        "test_dates": [str(test["date"].min().date()), str(test["date"].max().date())],
        "test_base_hit_rate": round(float(y_test.mean()), 3),
        "models": {},
    }
    base_probability = np.full(len(test), float(y_train.mean()))
    results["models"]["historical_base_rate"] = evaluate(
        y_test, base_probability, test["excess_return_20d"])
    models = {
        "shallow_tree": DecisionTreeClassifier(max_depth=3, min_samples_leaf=100, random_state=42),
        "random_forest": RandomForestClassifier(n_estimators=200, max_depth=5,
                                                 min_samples_leaf=40, random_state=42,
                                                 n_jobs=1),
        "gradient_boosting": HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=8,
                                                               min_samples_leaf=50,
                                                               random_state=42),
    }
    for name, estimator in models.items():
        model = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), estimator)
        model.fit(x_train, y_train)
        probabilities = model.predict_proba(x_test)[:, 1]
        results["models"][name] = evaluate(y_test, probabilities,
                                            test["excess_return_20d"])
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
