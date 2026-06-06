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
        height: 120px !important;
        width: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-sizing: border-box;
    ">
        <div style="color: #8b949e; font-size: 14px; font-weight: 500; line-height: 1.2;">{label}</div>
        <div style="color: {color}; font-size: 26px; font-weight: 600; line-height: 1.2;">{value_str}</div>
    </div>
    """

def render_plain_metric_card(label: str, value: str | int | float | None, format_str: str = "{}") -> str:
    """Renders a custom HTML/CSS metric card for standard values (price, symbols count, DMA)."""
    if value is None or pd.isna(value):
        val_display = "n/a"
    else:
        val_display = format_str.format(value)

    if isinstance(val_display, str) and " (" in val_display and val_display.endswith(")"):
        main_part, extra_part = val_display.split(" (", 1)
        extra_part = extra_part.rstrip(")")
        val_html = f'<span style="color: #f0f6fc;">{main_part}</span><span style="color: #8b949e; font-size: 16px; font-weight: 500; margin-left: 8px;">({extra_part})</span>'
    else:
        val_html = f'<span style="color: #f0f6fc;">{val_display}</span>'

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
        height: 120px !important;
        width: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-sizing: border-box;
    ">
        <div style="color: #8b949e; font-size: 14px; font-weight: 500; line-height: 1.2;">{label}</div>
        <div style="font-size: 26px; font-weight: 600; line-height: 1.2;">{val_html}</div>
    </div>
    """
