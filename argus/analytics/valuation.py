from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any


@dataclass(frozen=True)
class ValuationMetricSpec:
    name: str
    label: str


VALUATION_METRIC_SPECS = (
    ValuationMetricSpec("forward_pe", "Forward P/E"),
    ValuationMetricSpec("trailing_pe", "Trailing P/E"),
    ValuationMetricSpec("price_to_sales", "Price / Sales"),
    ValuationMetricSpec("ev_to_sales", "EV / Sales"),
    ValuationMetricSpec("ev_to_ebitda", "EV / EBITDA"),
    ValuationMetricSpec("ev_sales_to_growth", "EV/Sales / Growth"),
)
VALUATION_METRICS = tuple(spec.name for spec in VALUATION_METRIC_SPECS)

MIN_PEER_COUNT = 3
FUNDAMENTALS_MAX_AGE_DAYS = 120


@dataclass(frozen=True)
class ValuationPeerRow:
    company_id: int
    as_of_date: Any
    peer_group_type: str
    peer_group_key: str
    metric_name: str
    company_value: float | None
    peer_median: float | None
    peer_count: int
    percentile_rank: float | None
    premium_discount_pct: float | None
    valuation_flag: str


def is_positive_finite(value: Any) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return numeric > 0 and numeric not in {float("inf"), float("-inf")} and numeric == numeric


def compute_ev_sales_to_growth(ev_to_sales: Any, revenue_growth: Any) -> float | None:
    if not is_positive_finite(ev_to_sales) or not is_positive_finite(revenue_growth):
        return None
    return float(ev_to_sales) / float(revenue_growth)


def valuation_metric_label(metric_name: str) -> str:
    labels = {spec.name: spec.label for spec in VALUATION_METRIC_SPECS}
    return labels.get(metric_name, metric_name)


def compute_percentile_rank(company_value: float, peer_values: list[float]) -> float:
    """Return 0-100 percentile rank where lower multiple values are cheaper."""
    if len(peer_values) <= 1:
        return 100.0
    lower_count = sum(1 for value in peer_values if value < company_value)
    equal_count = sum(1 for value in peer_values if value == company_value)
    return (lower_count + 0.5 * equal_count) / len(peer_values) * 100.0


def valuation_flag_for_percentile(percentile_rank: float | None, peer_count: int) -> str:
    if percentile_rank is None or peer_count < MIN_PEER_COUNT:
        return "unavailable"
    if percentile_rank <= 30.0:
        return "cheap"
    if percentile_rank >= 70.0:
        return "stretched"
    return "neutral"


def build_peer_rows(
    fundamentals: list[dict[str, Any]],
    peer_memberships: list[dict[str, Any]],
) -> list[ValuationPeerRow]:
    fundamentals_by_company = {int(row["company_id"]): dict(row) for row in fundamentals}
    group_members: dict[tuple[str, str], list[int]] = {}
    for membership in peer_memberships:
        group_key = (str(membership["peer_group_type"]), str(membership["peer_group_key"]))
        group_members.setdefault(group_key, []).append(int(membership["company_id"]))

    rows: list[ValuationPeerRow] = []
    for (peer_group_type, peer_group_key), company_ids in group_members.items():
        for metric_name in VALUATION_METRICS:
            values_by_company: dict[int, float] = {}
            for company_id in company_ids:
                fundamental = fundamentals_by_company.get(company_id)
                if not fundamental:
                    continue
                raw_value = fundamental.get(metric_name)
                if is_positive_finite(raw_value):
                    values_by_company[company_id] = float(raw_value)

            for company_id in company_ids:
                fundamental = fundamentals_by_company.get(company_id)
                if not fundamental:
                    continue
                company_value = values_by_company.get(company_id)
                peer_values = [
                    value
                    for peer_company_id, value in values_by_company.items()
                    if peer_company_id != company_id
                ]
                peer_count = len(peer_values)
                peer_median = median(peer_values) if peer_count >= MIN_PEER_COUNT else None
                percentile_rank = (
                    compute_percentile_rank(company_value, peer_values)
                    if company_value is not None and peer_count >= MIN_PEER_COUNT
                    else None
                )
                premium_discount_pct = (
                    (company_value / peer_median - 1.0)
                    if company_value is not None and peer_median
                    else None
                )
                rows.append(
                    ValuationPeerRow(
                        company_id=company_id,
                        as_of_date=fundamental["as_of_date"],
                        peer_group_type=peer_group_type,
                        peer_group_key=peer_group_key,
                        metric_name=metric_name,
                        company_value=company_value,
                        peer_median=peer_median,
                        peer_count=peer_count,
                        percentile_rank=percentile_rank,
                        premium_discount_pct=premium_discount_pct,
                        valuation_flag=valuation_flag_for_percentile(percentile_rank, peer_count),
                    )
                )
    return rows
