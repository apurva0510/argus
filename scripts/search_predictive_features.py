"""Read-only rolling evaluation of feature families for 20-session QQQ outperformance."""

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.inspection import permutation_importance
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from argus.analytics.predictive_signals import build_dataset, load_history
from argus.core.db import get_engine

MOMENTUM = ("return_1w", "return_1m", "return_3m",
            "relative_return_vs_qqq_1m", "relative_return_vs_qqq_3m")
PULLBACK = ("rsi_14", "drawdown_52w", "distance_from_50dma",
            "distance_from_200dma", "volatility_20d")
MARKET = ("qqq_return_1m", "qqq_return_3m", "qqq_volatility_20d")
RANKS = ("drawdown_52w_daily_rank", "relative_return_vs_qqq_3m_daily_rank",
         "rsi_14_daily_rank")
MINIMUM_HIT_RATE = 0.70
FEATURE_SETS = {
    "volatility_only": ("volatility_20d",),
    "volatility_rsi": ("volatility_20d", "rsi_14"),
    "volatility_market": ("volatility_20d",) + MARKET,
    "momentum": MOMENTUM,
    "pullback": PULLBACK,
    "technical_all": MOMENTUM + PULLBACK,
    "technical_qqq_1m": MOMENTUM + PULLBACK + ("qqq_return_1m",),
    "technical_qqq_3m": MOMENTUM + PULLBACK + ("qqq_return_3m",),
    "technical_qqq_volatility": MOMENTUM + PULLBACK + ("qqq_volatility_20d",),
    "technical_market": MOMENTUM + PULLBACK + MARKET,
    "technical_market_ranks": MOMENTUM + PULLBACK + MARKET + RANKS,
}


def eligible_models(folds: list[dict], minimum_hit_rate: float = MINIMUM_HIT_RATE) -> list[str]:
    """Require the hit-rate threshold in every held-out window."""
    if not folds:
        return []
    return [
        name for name in folds[0]["models"]
        if all(fold["models"][name]["daily_top_five_hit_rate"] >= minimum_hit_rate
               for fold in folds)
    ]


def rolling_folds(data: pd.DataFrame, n_folds: int = 4, first_train_fraction: float = 0.5):
    """Expanding train windows and disjoint test dates with matured training labels."""
    dates = np.array(sorted(data["date"].unique()))
    first = int(len(dates) * first_train_fraction)
    if len(dates) < 120 or first < 60:
        raise ValueError("Not enough dated examples for rolling validation")
    boundaries = np.linspace(first, len(dates), n_folds + 1, dtype=int)
    for index in range(n_folds):
        start, end = dates[boundaries[index]], dates[boundaries[index + 1] - 1]
        train = data.loc[data["label_end"] < start]
        test = data.loc[(data["date"] >= start) & (data["date"] <= end)]
        if train.empty or test.empty:
            raise ValueError("Fold has no training or test data")
        yield train, test


def _model(kind: str):
    if kind == "logistic":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LogisticRegression(max_iter=1000))
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        RandomForestClassifier(n_estimators=150, max_depth=4, min_samples_leaf=60,
                               random_state=42, n_jobs=1),
    )


def _daily_top_five(test: pd.DataFrame, probabilities: np.ndarray) -> tuple[float, float]:
    ranked = test[["date", "outperformed_qqq", "excess_return_20d"]].copy()
    ranked["probability"] = probabilities
    picks = ranked.sort_values(["date", "probability"], ascending=[True, False])
    picks = picks.groupby("date", sort=False).head(5)
    return float(picks["outperformed_qqq"].mean()), float(picks["excess_return_20d"].mean())


def _cohorts(test: pd.DataFrame, probabilities: np.ndarray) -> dict:
    result = {}
    masks = {
        "pullback_zone": (test["drawdown_52w"] <= -0.10) & (test["rsi_14"] <= 55),
        "outside_pullback_zone": (test["drawdown_52w"] > -0.10) | (test["rsi_14"] > 55),
    }
    for name, mask in masks.items():
        subset = test.loc[mask]
        if len(subset) < 100 or subset["outperformed_qqq"].nunique() < 2:
            continue
        probs = probabilities[np.asarray(mask)]
        hit, excess = _daily_top_five(subset, probs)
        result[name] = {
            "rows": len(subset),
            "base_hit_rate": round(float(subset["outperformed_qqq"].mean()), 3),
            "auc": round(float(roc_auc_score(subset["outperformed_qqq"], probs)), 3),
            "daily_top_five_hit_rate": round(hit, 3),
            "daily_top_five_excess_return": round(excess, 4),
        }
    return result


def main():
    with get_engine().connect() as connection:
        bars, metrics = load_history(connection)
    data = build_dataset(bars, metrics)
    output = {"dataset_rows": len(data), "folds": [], "summary": []}
    for fold_number, (train, test) in enumerate(rolling_folds(data), start=1):
        y_train, y_test = train["outperformed_qqq"], test["outperformed_qqq"]
        fold = {
            "fold": fold_number,
            "train_end": str(train["date"].max().date()),
            "test_start": str(test["date"].min().date()),
            "test_end": str(test["date"].max().date()),
            "test_rows": len(test),
            "base_hit_rate": round(float(y_test.mean()), 3),
            "models": {},
        }
        for family, features in FEATURE_SETS.items():
            for kind in ("logistic", "forest"):
                model = _model(kind)
                model.fit(train[list(features)], y_train)
                probabilities = model.predict_proba(test[list(features)])[:, 1]
                hit, excess = _daily_top_five(test, probabilities)
                fold["models"][f"{family}_{kind}"] = {
                    "auc": round(float(roc_auc_score(y_test, probabilities)), 3),
                    "brier": round(float(brier_score_loss(y_test, probabilities)), 3),
                    "daily_top_five_hit_rate": round(hit, 3),
                    "daily_top_five_mean_excess_return": round(excess, 4),
                }
                if family == "volatility_market" and kind == "forest":
                    fold["product_cohorts"] = _cohorts(test, probabilities)
                    if fold_number == 4:
                        importance = permutation_importance(
                            model, test[list(features)], y_test, scoring="roc_auc",
                            n_repeats=3, random_state=42, n_jobs=1,
                        )
                        fold["permutation_auc_drop"] = {
                            feature: round(float(drop), 4)
                            for feature, drop in zip(features, importance.importances_mean)
                        }
        output["folds"].append(fold)
    for name in output["folds"][0]["models"]:
        values = [fold["models"][name] for fold in output["folds"]]
        output["summary"].append({
            "model": name,
            "mean_auc": round(float(np.mean([v["auc"] for v in values])), 3),
            "min_auc": min(v["auc"] for v in values),
            "mean_brier": round(float(np.mean([v["brier"] for v in values])), 3),
            "mean_daily_top_five_hit_rate": round(float(np.mean([
                v["daily_top_five_hit_rate"] for v in values])), 3),
            "mean_daily_top_five_excess_return": round(float(np.mean([
                v["daily_top_five_mean_excess_return"] for v in values])), 4),
        })
    output["summary"].sort(key=lambda row: row["mean_auc"], reverse=True)
    output["promotion_gate"] = {
        "metric": "daily top-five 20-session QQQ outperformance hit rate",
        "minimum_each_held_out_fold": MINIMUM_HIT_RATE,
        "eligible_models": eligible_models(output["folds"]),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
