from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

THEME_EXPOSURE_MAX = 25.0
PULLBACK_MAX = 25.0
TECHNICAL_SETUP_MAX = 20.0
RELATIVE_STRENGTH_MAX = 15.0
CATALYST_MAX = 10.0
WATCHLIST_PRIORITY_MAX = 5.0
RISK_PENALTY_MIN = -30.0

WATCH_STATUS_SCORES: dict[str, float] = {
    "high_priority": 5.0,
    "owned": 4.0,
    "watch": 3.0,
    "ignore": 0.0,
}


RATE_SENSITIVE_SECTORS: set[str] = {
    "Power and Grid",
    "Energy, Nuclear, and Utilities",
    "Cooling and Data Center Infrastructure",
}


def _is_missing(value: Any) -> bool:
    """Check if value is None, pd.NA, or numpy/pandas NaN."""
    return value is None or pd.isna(value)


def score_theme_exposure(theme_exposure_score: float | None) -> tuple[float, list[str]]:
    if _is_missing(theme_exposure_score):
        return 0.0, ["Theme exposure score unavailable"]

    clamped = max(0.0, min(5.0, float(theme_exposure_score)))
    score = clamped / 5.0 * THEME_EXPOSURE_MAX
    return score, [f"Theme exposure {clamped:.1f}/5"]


def score_pullback(drawdown_52w: float | None) -> tuple[float, list[str]]:
    if _is_missing(drawdown_52w):
        return 0.0, ["52-week drawdown unavailable"]

    drawdown = float(drawdown_52w)
    magnitude = abs(min(0.0, drawdown))
    if magnitude < 0.10:
        return 0.0, [
            f"Only {magnitude * 100:.1f}% below 52W high (need at least 10% for pullback score)"
        ]

    if magnitude >= 0.30:
        return PULLBACK_MAX, [f"Down {magnitude * 100:.1f}% from 52-week high"]

    score = (magnitude - 0.10) / 0.20 * PULLBACK_MAX
    return score, [f"Down {magnitude * 100:.1f}% from 52-week high"]


def score_technical_setup(
    rsi_14: float | None,
    distance_from_200dma: float | None,
) -> tuple[float, list[str]]:
    rsi_points = 0.0
    dma_points = 0.0
    reasons: list[str] = []

    if _is_missing(rsi_14):
        reasons.append("RSI unavailable")
    else:
        rsi = float(rsi_14)
        if rsi <= 30:
            rsi_points = 10.0
            reasons.append(f"RSI {rsi:.0f} (oversold)")
        elif rsi <= 40:
            rsi_points = 8.0
            reasons.append(f"RSI {rsi:.0f} (pullback zone)")
        elif rsi <= 45:
            rsi_points = 6.0
            reasons.append(f"RSI {rsi:.0f} (moderate pullback)")
        elif rsi <= 55:
            rsi_points = 3.0
            reasons.append(f"RSI {rsi:.0f} (neutral)")
        else:
            reasons.append(f"RSI {rsi:.0f} (not oversold)")

    if _is_missing(distance_from_200dma):
        reasons.append("200DMA distance unavailable")
    else:
        distance = float(distance_from_200dma)
        if distance >= 0.05:
            dma_points = 10.0
            reasons.append(f"Price {distance * 100:.1f}% above 200DMA")
        elif distance >= 0.0:
            dma_points = 8.0
            reasons.append("Still above 200DMA")
        elif distance >= -0.05:
            dma_points = 5.0
            reasons.append(f"Near 200DMA ({distance * 100:.1f}%)")
        elif distance >= -0.10:
            dma_points = 2.0
            reasons.append(f"Slightly below 200DMA ({distance * 100:.1f}%)")
        else:
            reasons.append(f"Well below 200DMA ({distance * 100:.1f}%)")

    return rsi_points + dma_points, reasons


def score_relative_strength(relative_return_vs_qqq_3m: float | None) -> tuple[float, list[str]]:
    if _is_missing(relative_return_vs_qqq_3m):
        return 0.0, ["3M relative return vs QQQ unavailable"]

    relative = float(relative_return_vs_qqq_3m)
    if relative >= 0.10:
        return RELATIVE_STRENGTH_MAX, [f"Outperforming QQQ by {relative * 100:.1f}% over 3M"]
    if relative >= 0.05:
        return 12.0, [f"Outperforming QQQ by {relative * 100:.1f}% over 3M"]
    if relative >= 0.0:
        return 8.0, [f"Slightly outperforming QQQ ({relative * 100:+.1f}%) over 3M"]
    if relative >= -0.05:
        return 3.0, [f"Slightly underperforming QQQ ({relative * 100:+.1f}%) over 3M"]
    return 0.0, [f"Underperforming QQQ by {abs(relative) * 100:.1f}% over 3M"]


def score_catalyst(
    *,
    recent_news_count: int | None = None,
    recent_filing_count: int | None = None,
    upcoming_earnings_days: int | None = None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    news_count = 0 if _is_missing(recent_news_count) else max(0, int(recent_news_count))
    filing_count = 0 if _is_missing(recent_filing_count) else max(0, int(recent_filing_count))

    if news_count > 0:
        score += min(4.0, float(news_count))
        reasons.append(f"{news_count} recent news item(s)")

    if filing_count > 0:
        score += min(3.0, filing_count * 1.5)
        reasons.append(f"{filing_count} recent SEC filing(s)")

    if not _is_missing(upcoming_earnings_days) and 0 <= int(upcoming_earnings_days) <= 14:
        score += 3.0
        reasons.append(f"Earnings in {int(upcoming_earnings_days)} days")

    if not reasons:
        reasons.append("No recent catalyst signals tracked yet")

    return min(CATALYST_MAX, score), reasons


def score_watchlist_priority(watch_status: str | None) -> tuple[float, list[str]]:
    if watch_status is None:
        return 0.0, ["Watch status: none"]
    status = watch_status.strip().lower()
    score = WATCH_STATUS_SCORES.get(status, 0.0)
    label = status.replace("_", " ")
    if score > 0:
        return score, [f"Watch status: {label}"]
    return score, [f"Watch status: {label} (low priority)"]


def score_risk_penalty(
    *,
    drawdown_52w: float | None,
    distance_from_200dma: float | None,
    return_1w: float | None,
) -> tuple[float, list[str]]:
    penalty = 0.0
    reasons: list[str] = []

    if not _is_missing(distance_from_200dma):
        distance = float(distance_from_200dma)
        if distance < -0.20:
            penalty -= 15.0
            reasons.append("Breakdown risk (severe distance below 200DMA)")
        elif distance < -0.10:
            penalty -= 8.0
            reasons.append("Below 200DMA risk flag")

    if not _is_missing(drawdown_52w):
        magnitude = abs(min(0.0, float(drawdown_52w)))
        if magnitude >= 0.45:
            penalty -= 10.0
            reasons.append("Severe drawdown risk (>45%)")
        elif magnitude >= 0.35:
            penalty -= 5.0
            reasons.append("Deep drawdown risk (>35%)")

    if not _is_missing(return_1w):
        weekly_return = float(return_1w)
        if weekly_return <= -0.15:
            penalty -= 5.0
            reasons.append("Sharp weekly decline risk")

    penalty = max(RISK_PENALTY_MIN, penalty)
    if not reasons:
        reasons.append("No major risk flags")
    return penalty, reasons


@dataclass
class ScoreInputs:
    theme_exposure_score: float | None = None
    drawdown_52w: float | None = None
    rsi_14: float | None = None
    distance_from_200dma: float | None = None
    relative_return_vs_qqq_3m: float | None = None
    watch_status: str | None = None
    recent_news_count: int | None = None
    recent_filing_count: int | None = None
    upcoming_earnings_days: int | None = None
    return_1w: float | None = None
    macro_pressure_level: int | None = None
    sector: str | None = None


@dataclass
class ScoreBreakdown:
    theme_exposure: float
    pullback: float
    technical_setup: float
    relative_strength: float
    catalyst: float
    watchlist_priority: float
    risk_penalty: float
    macro_penalty: float
    opportunity_score: float
    explanation: str
    reason_lines: list[str] = field(default_factory=list)


def build_explanation(reason_lines: list[str]) -> str:
    return " | ".join(reason_lines)


def score_macro_penalty(
    macro_pressure_level: int | None,
    sector: str | None,
) -> tuple[float, list[str]]:
    if _is_missing(macro_pressure_level) or int(macro_pressure_level) == 0:
        return 0.0, []

    level = int(macro_pressure_level)
    pressure_map = {
        1: -3.0,
        2: -6.0,
        3: -10.0,
    }
    base_penalty = pressure_map.get(level, 0.0)
    if base_penalty == 0.0:
        return 0.0, []

    # Only apply penalty to rate-sensitive sectors
    if sector in RATE_SENSITIVE_SECTORS:
        penalty = base_penalty
        sector_desc = "rate-sensitive"
    else:
        penalty = 0.0
        sector_desc = "non-rate-sensitive"

    if penalty == 0.0:
        return 0.0, []

    pressure_names = {1: "Mild", 2: "High", 3: "Severe"}
    pressure_name = pressure_names.get(level, "Unknown")
    reason = f"Macro penalty: {penalty:.1f} ({pressure_name} pressure, {sector_desc} sector)"
    return penalty, [reason]


def compute_opportunity_score(inputs: ScoreInputs) -> ScoreBreakdown:
    theme_score, theme_reasons = score_theme_exposure(inputs.theme_exposure_score)
    pullback_score, pullback_reasons = score_pullback(inputs.drawdown_52w)
    technical_score, technical_reasons = score_technical_setup(
        inputs.rsi_14,
        inputs.distance_from_200dma,
    )
    relative_score, relative_reasons = score_relative_strength(inputs.relative_return_vs_qqq_3m)
    catalyst_score, catalyst_reasons = score_catalyst(
        recent_news_count=inputs.recent_news_count,
        recent_filing_count=inputs.recent_filing_count,
        upcoming_earnings_days=inputs.upcoming_earnings_days,
    )
    watchlist_score, watchlist_reasons = score_watchlist_priority(inputs.watch_status)
    risk_penalty, risk_reasons = score_risk_penalty(
        drawdown_52w=inputs.drawdown_52w,
        distance_from_200dma=inputs.distance_from_200dma,
        return_1w=inputs.return_1w,
    )
    macro_penalty, macro_reasons = score_macro_penalty(
        inputs.macro_pressure_level,
        inputs.sector,
    )

    reason_lines = [
        *theme_reasons,
        *pullback_reasons,
        *technical_reasons,
        *relative_reasons,
        *catalyst_reasons,
        *watchlist_reasons,
        *risk_reasons,
        *macro_reasons,
    ]

    opportunity_score = (
        theme_score
        + pullback_score
        + technical_score
        + relative_score
        + catalyst_score
        + watchlist_score
        + risk_penalty
        + macro_penalty
    )

    return ScoreBreakdown(
        theme_exposure=theme_score,
        pullback=pullback_score,
        technical_setup=technical_score,
        relative_strength=relative_score,
        catalyst=catalyst_score,
        watchlist_priority=watchlist_score,
        risk_penalty=risk_penalty,
        macro_penalty=macro_penalty,
        opportunity_score=opportunity_score,
        explanation=build_explanation(reason_lines),
        reason_lines=reason_lines,
    )
