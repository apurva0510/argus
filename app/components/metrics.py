from __future__ import annotations
import pandas as pd

def render_metric_card(label: str, value: float | None, is_percentage: bool = True) -> str:
    """Renders a custom HTML/CSS metric card for returns and percentages.
    Displays positive returns in green (+X.XX%), negative in red (-X.XX%), and zero/null in gray.
    """
    if value is None or pd.isna(value):
        value_str = "n/a"
        color = "#8b949e"  # Gray
    else:
        if is_percentage:
            value_str = f"{value * 100:+.2f}%"
        else:
            value_str = f"{value:+.1f}"

        if value > 0:
            color = "#3fb950"  # Green
        elif value < 0:
            color = "#f85149"  # Red
        else:
            color = "#8b949e"  # Gray

    return f"""
    <div style="
        background: rgba(22, 27, 34, 0.6);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(240, 246, 252, 0.1);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
    ">
        <div style="color: #8b949e; font-size: 14px; font-weight: 500; margin-bottom: 8px;">{label}</div>
        <div style="color: {color}; font-size: 28px; font-weight: 600; line-height: 1.2;">{value_str}</div>
    </div>
    """

def render_plain_metric_card(label: str, value: str | int | float | None, format_str: str = "{}") -> str:
    """Renders a custom HTML/CSS metric card for standard values (price, symbols count, DMA)."""
    if value is None or pd.isna(value):
        val_display = "n/a"
    else:
        val_display = format_str.format(value)

    return f"""
    <div style="
        background: rgba(22, 27, 34, 0.6);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(240, 246, 252, 0.1);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
    ">
        <div style="color: #8b949e; font-size: 14px; font-weight: 500; margin-bottom: 8px;">{label}</div>
        <div style="color: #f0f6fc; font-size: 28px; font-weight: 600; line-height: 1.2;">{val_display}</div>
    </div>
    """
