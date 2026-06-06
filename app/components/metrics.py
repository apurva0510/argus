from __future__ import annotations

from html import escape

import pandas as pd


def _metric_card_shell(
    label: str,
    value_html: str,
    value_color: str | None = None,
    value_font_size: int = 26,
) -> str:
    color_style = f"color: {value_color};" if value_color else ""
    safe_label = escape(label, quote=True).upper()
    return f"""
    <div style="
        background: linear-gradient(135deg, rgba(22, 27, 34, 0.4) 0%, rgba(17, 22, 29, 0.5) 100%);
        border: 1px solid rgba(240, 246, 252, 0.1);
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
        height: 120px !important;
        width: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-sizing: border-box;
    ">
        <div style="color: #8b949e; font-size: 11px; font-weight: 600; line-height: 1.1; text-transform: uppercase; letter-spacing: 0.6px;">{safe_label}</div>
        <div style="{color_style} font-size: {value_font_size}px; font-weight: 600; line-height: 1.2;">{value_html}</div>
    </div>
    """


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

    return _metric_card_shell(label, escape(value_str, quote=True), color)


def render_plain_metric_card(
    label: str,
    value: str | int | float | None,
    format_str: str = "{}",
    value_font_size: int = 26,
) -> str:
    """Renders a custom HTML/CSS metric card for standard values (price, symbols count, DMA)."""
    if value is None or pd.isna(value):
        val_display = "n/a"
    else:
        val_display = format_str.format(value)

    if isinstance(val_display, str) and " (" in val_display and val_display.endswith(")"):
        main_part, extra_part = val_display.split(" (", 1)
        main_part = escape(main_part, quote=True)
        extra_part = escape(extra_part.rstrip(")"), quote=True)
        val_html = f'<span style="color: #f0f6fc;">{main_part}</span><span style="color: #8b949e; font-size: 16px; font-weight: 500; margin-left: 8px;">({extra_part})</span>'
    else:
        val_html = f'<span style="color: #f0f6fc;">{escape(str(val_display), quote=True)}</span>'

    return _metric_card_shell(label, val_html, value_font_size=value_font_size)


def render_plain_metric_card_html(label: str, value_html: str) -> str:
    """Render a plain metric card when the value HTML is built from controlled markup."""
    return _metric_card_shell(label, value_html)


def render_plain_metric_card_parts(
    label: str,
    primary: str,
    secondary: str,
    *,
    secondary_color: str = "#8b949e",
    value_font_size: int = 26,
) -> str:
    """Render a plain metric card with a smaller secondary value beside the primary value."""
    val_html = (
        f'<span style="color: #f0f6fc;">{escape(primary, quote=True)}</span>'
        f'<span style="color: {secondary_color}; font-size: 16px; font-weight: 500; margin-left: 8px;">'
        f"({escape(secondary, quote=True)})</span>"
    )
    return _metric_card_shell(label, val_html, value_font_size=value_font_size)
