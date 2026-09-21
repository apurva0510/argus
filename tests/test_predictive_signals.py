from datetime import date, timedelta

import pandas as pd
import pytest

from argus.analytics.predictive_signals import build_dataset, chronological_split
from argus.analytics.pullback_outcomes import build_pullback_events
from scripts.search_predictive_features import eligible_models, rolling_folds
from scripts.experiment_pullback_recovery import selection_report


def _history(days=100):
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(days)]
    bars = pd.DataFrame([
        {"company_id": company_id, "symbol": symbol, "is_benchmark": benchmark,
         "date": day, "adj_close": 100 + i * multiplier}
        for company_id, symbol, benchmark, multiplier in
        [(1, "QQQ", True, 1), (2, "ABC", False, 2)]
        for i, day in enumerate(dates)
    ])
    metrics = pd.DataFrame([
        {"company_id": 2, "date": day, "rsi_14": 40,
         "drawdown_52w": -0.2, "relative_return_vs_qqq_3m": 0.1}
        for day in dates
    ])
    return bars, metrics


def test_dataset_uses_matured_future_prices_and_excludes_benchmark():
    bars, metrics = _history()
    data = build_dataset(bars, metrics, horizon=20)
    assert len(data) == 80
    assert set(data["symbol"]) == {"ABC"}
    assert data.iloc[0]["label_end"] == pd.Timestamp("2025-01-21")
    assert data.iloc[0]["excess_return_20d"] == pytest.approx(0.2)
    assert data.iloc[0]["outperformed_qqq"] == 1


def test_split_embargoes_unmatured_training_labels():
    bars, metrics = _history()
    data = build_dataset(bars, metrics, horizon=1)
    train, test = chronological_split(data)
    assert train["label_end"].max() < test["date"].min()
    assert train["date"].max() < test["date"].min()


def test_missing_company_session_is_not_labeled_against_wrong_qqq_window():
    bars, metrics = _history()
    bars = bars.loc[~((bars["symbol"] == "ABC") & (bars["date"] == date(2025, 1, 11)))]
    data = build_dataset(bars, metrics, horizon=2)
    assert date(2025, 1, 9) not in set(data["date"].dt.date)


def test_market_features_and_daily_ranks_use_signal_day_information():
    bars, metrics = _history()
    data = build_dataset(bars, metrics, horizon=2)
    assert data.iloc[63]["qqq_return_3m"] == pytest.approx(0.63)
    assert data.iloc[63]["relative_return_vs_qqq_3m_daily_rank"] == 1.0


def test_rolling_folds_have_disjoint_test_dates_and_mature_training_labels():
    bars, metrics = _history(days=160)
    data = build_dataset(bars, metrics, horizon=1)
    folds = list(rolling_folds(data, n_folds=2))
    for train, test in folds:
        assert train["label_end"].max() < test["date"].min()
    assert folds[0][1]["date"].max() < folds[1][1]["date"].min()


def test_promotion_requires_seventy_percent_in_every_fold():
    folds = [
        {"models": {"steady": {"daily_top_five_hit_rate": 0.71},
                    "uneven": {"daily_top_five_hit_rate": 0.82}}},
        {"models": {"steady": {"daily_top_five_hit_rate": 0.70},
                    "uneven": {"daily_top_five_hit_rate": 0.69}}},
    ]
    assert eligible_models(folds) == ["steady"]


def test_pullback_outcome_uses_next_open_and_flags_interim_breakdown():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(70)]
    rows = []
    for i, day in enumerate(dates):
        for cid, symbol, benchmark in [(1, "QQQ", True), (2, "ABC", False)]:
            close = 100 if benchmark else (90 if i == 10 else (100 if i == 0 else 120))
            entry_open = 100 if benchmark else (110 if i == 1 else close)
            rows.append({"company_id": cid, "symbol": symbol,
                         "is_benchmark": benchmark, "date": day,
                         "open": entry_open, "close": close, "adj_close": close})
    bars = pd.DataFrame(rows)
    metrics = pd.DataFrame([{
        "company_id": 2, "date": day,
        "drawdown_52w": -0.15 if i == 0 else -0.05,
        "rsi_14": 40, "distance_from_200dma": 0.02,
        "relative_return_vs_qqq_3m": 0.1, "volatility_20d": 0.2,
    } for i, day in enumerate(dates)])
    events = build_pullback_events(bars, metrics, horizon=60)
    assert len(events) == 1
    event = events.iloc[0]
    assert event["entry_date"] == pd.Timestamp("2025-01-02")
    assert event["company_return"] == pytest.approx(120 / 110 - 1)
    assert event["worst_close_return"] == pytest.approx(90 / 110 - 1)
    assert event["breakdown"] == 1
    assert event["healthy_recovery"] == 0
    healthy_bars = bars.copy()
    healthy_bars.loc[
        (healthy_bars["symbol"] == "ABC") & (healthy_bars["date"] == dates[10]),
        ["open", "close", "adj_close"],
    ] = 115
    healthy = build_pullback_events(healthy_bars, metrics, horizon=60).iloc[0]
    assert healthy["breakdown"] == 0
    assert healthy["healthy_recovery"] == 1


def test_signal_gate_reports_coverage_and_rejects_repeated_company():
    dates = pd.date_range("2025-01-01", periods=40)
    repeated = pd.DataFrame({"company_id": [1] * 40, "date": dates})
    labels = pd.Series([1] * 36 + [0] * 4)
    report = selection_report(labels, pd.Series([True] * 40), repeated)
    assert report["hit_rate"] == 0.9
    assert report["coverage"] == 1.0
    assert report["companies"] == 1
    assert report["passes_gate"] is False

    diverse = repeated.copy()
    diverse["company_id"] = [i % 10 for i in range(40)]
    report = selection_report(labels, pd.Series([True] * 40), diverse)
    assert report["passes_gate"] is True
