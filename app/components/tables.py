import pandas as pd


def style_positive_green_negative_red(val):
    """Pandas Styler function to color positive values green and negative values red.
    Handles both numbers and formatted percentage string types.
    """
    if val is None or pd.isna(val):
        return ""
    if isinstance(val, str):
        val_clean = val.strip()
        if val_clean.startswith("+"):
            return "color: #3fb950; font-weight: 600;"
        elif val_clean.startswith("-"):
            return "color: #f85149; font-weight: 600;"
    elif isinstance(val, (int, float)):
        if val > 0:
            return "color: #3fb950; font-weight: 600;"
        elif val < 0:
            return "color: #f85149; font-weight: 600;"
    return ""


def style_positive_red_negative_green(val):
    """Color positive values red and negative values green for inverse metrics.

    Useful for valuation premium/discount where paying a premium is usually bad
    and trading at a discount is usually good.
    """
    if val is None or pd.isna(val):
        return ""
    if isinstance(val, str):
        val_clean = val.strip()
        if val_clean.startswith("+"):
            return "color: #f85149; font-weight: 600;"
        elif val_clean.startswith("-"):
            return "color: #3fb950; font-weight: 600;"
    elif isinstance(val, (int, float)):
        if val > 0:
            return "color: #f85149; font-weight: 600;"
        elif val < 0:
            return "color: #3fb950; font-weight: 600;"
    return ""


def style_score_traffic_light(val):
    """Color opportunity scores as red/yellow/green traffic-light bands."""
    if val is None or pd.isna(val):
        return ""
    try:
        score = float(str(val).strip())
    except (TypeError, ValueError):
        return ""
    if score >= 70:
        return "color: #3fb950; font-weight: 700;"
    if score >= 40:
        return "color: #f0b429; font-weight: 700;"
    return "color: #f85149; font-weight: 700;"
