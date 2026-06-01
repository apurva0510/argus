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
