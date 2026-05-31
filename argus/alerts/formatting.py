from __future__ import annotations

from datetime import UTC, datetime
from argus.core.models import Alert, Company


def format_alert_email(
    alert: Alert, company: Company, payload: dict
) -> tuple[str, str, str]:
    """Format an alert event into plain text and HTML bodies.

    Returns:
        tuple[str, str, str]: (subject, plain_text_body, html_body)
    """
    rule_type = alert.rule_type
    symbol = company.symbol
    company_name = company.name
    alert_name = alert.name

    # Determine details
    text_details = ""
    html_details = ""

    if rule_type == "price_below":
        price = payload.get("price", 0.0)
        threshold = payload.get("threshold", 0.0)
        text_details = f"Price of {symbol} (${price:.2f}) dropped below the threshold of ${threshold:.2f}."
        html_details = f"Price of <strong>{symbol}</strong> (<strong>${price:.2f}</strong>) dropped below the threshold of <strong>${threshold:.2f}</strong>."

    elif rule_type == "price_above":
        price = payload.get("price", 0.0)
        threshold = payload.get("threshold", 0.0)
        text_details = f"Price of {symbol} (${price:.2f}) rose above the threshold of ${threshold:.2f}."
        html_details = f"Price of <strong>{symbol}</strong> (<strong>${price:.2f}</strong>) rose above the threshold of <strong>${threshold:.2f}</strong>."

    elif rule_type == "daily_move_gt":
        ret = payload.get("return_1d") or 0.0
        ret_pct = ret * 100.0
        threshold_pct = payload.get("threshold_pct", 0.0)
        text_details = f"Daily return of {symbol} ({ret_pct:+.2f}%) exceeded the absolute move threshold of {threshold_pct:.2f}%."
        html_details = f"Daily return of <strong>{symbol}</strong> (<strong>{ret_pct:+.2f}%</strong>) exceeded the absolute move threshold of <strong>{threshold_pct:.2f}%</strong>."

    elif rule_type == "drawdown_52w_gt":
        dd = payload.get("drawdown_52w") or 0.0
        dd_pct = abs(dd) * 100.0
        threshold_pct = payload.get("threshold_pct", 0.0)
        text_details = f"52-week drawdown of {symbol} ({dd_pct:.2f}%) exceeded the threshold of {threshold_pct:.2f}%."
        html_details = f"52-week drawdown of <strong>{symbol}</strong> (<strong>{dd_pct:.2f}%</strong>) exceeded the threshold of <strong>{threshold_pct:.2f}%</strong>."

    elif rule_type == "rsi_below":
        rsi = payload.get("rsi_14") or 0.0
        threshold = payload.get("threshold", 0.0)
        text_details = f"RSI 14 of {symbol} ({rsi:.1f}) fell below the threshold of {threshold:.1f}."
        html_details = f"RSI 14 of <strong>{symbol}</strong> (<strong>{rsi:.1f}</strong>) fell below the threshold of <strong>{threshold:.1f}</strong>."

    elif rule_type in ("crossed_50dma", "crossed_200dma"):
        ma_type = "50DMA" if rule_type == "crossed_50dma" else "200DMA"
        price = payload.get("price", 0.0)
        ma_val = payload.get("ma_50") or payload.get("ma_200") or 0.0
        direction = payload.get("direction", "any")
        text_details = f"Price of {symbol} (${price:.2f}) crossed its {ma_type} (${ma_val:.2f}) (direction: {direction})."
        html_details = f"Price of <strong>{symbol}</strong> (<strong>${price:.2f}</strong>) crossed its <strong>{ma_type}</strong> (<strong>${ma_val:.2f}</strong>) (direction: <strong>{direction}</strong>)."

    elif rule_type == "new_sec_filing":
        form = payload.get("form", "Unknown")
        filing_date = payload.get("filing_date") or "Unknown"
        acc_no = payload.get("accession_no", "")
        url = payload.get("primary_doc_url", "")
        text_details = f"New SEC Filing for {symbol}: Form {form} filed on {filing_date}. Accession: {acc_no}. URL: {url}"
        html_details = (
            f"New SEC Filing for <strong>{symbol}</strong>:<br/>"
            f"<strong>Form:</strong> {form}<br/>"
            f"<strong>Filing Date:</strong> {filing_date}<br/>"
            f"<strong>Accession No:</strong> {acc_no}<br/>"
            f"<strong>Filing Document:</strong> <a href='{url}'>{url}</a>"
        )

    elif rule_type == "news_keyword_match":
        title = payload.get("title", "")
        url = payload.get("url", "")
        published = payload.get("published_at") or "Unknown"
        text_details = f"News keyword match for {symbol}:\nTitle: {title}\nPublished: {published}\nURL: {url}"
        html_details = (
            f"News match for <strong>{symbol}</strong>:<br/>"
            f"<strong>Title:</strong> <a href='{url}'>{title}</a><br/>"
            f"<strong>Published:</strong> {published}"
        )

    elif rule_type == "earnings_within_days":
        fp = payload.get("fiscal_period") or "Unknown"
        days_until = payload.get("days_until", 0)
        event_date = payload.get("event_date") or "Unknown"
        text_details = f"Upcoming earnings for {symbol} ({fp}) in {days_until} days on {event_date}."
        html_details = f"Upcoming earnings for <strong>{symbol}</strong> (<strong>{fp}</strong>) in <strong>{days_until}</strong> days on <strong>{event_date}</strong>."

    elif rule_type == "entered_pullback_zone":
        dd = payload.get("drawdown_52w") or 0.0
        dd_pct = abs(dd) * 100.0
        rsi = payload.get("rsi_14") or 0.0
        dist = payload.get("distance_from_200dma") or 0.0
        dist_pct = dist * 100.0
        text_details = (
            f"Stock {symbol} entered the pullback zone:\n"
            f"Drawdown: -{dd_pct:.1f}%\n"
            f"RSI 14: {rsi:.1f}\n"
            f"Distance to 200DMA: {dist_pct:+.1f}%"
        )
        html_details = (
            f"Stock <strong>{symbol}</strong> entered the pullback zone:<br/>"
            f"• <strong>Drawdown:</strong> -{dd_pct:.1f}%<br/>"
            f"• <strong>RSI 14:</strong> {rsi:.1f}<br/>"
            f"• <strong>Distance to 200DMA:</strong> {dist_pct:+.1f}%"
        )

    else:
        text_details = f"Alert triggered for {symbol}: {payload}"
        html_details = f"Alert triggered for <strong>{symbol}</strong>: {payload}"

    # Build subject line
    subject = f"[Argus Alert] {symbol} - {alert_name} triggered ({rule_type})"

    # Timestamp
    timestamp_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    local_timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Detail URL link
    detail_url = f"http://localhost:8501/Company_Detail?ticker={symbol}"

    # Build plain text body
    plain_text_body = f"""Argus Alert Triggered

Company: {company_name} ({symbol})
Alert: {alert_name}
Rule: {rule_type}

Details:
{text_details}

View Company Detail: {detail_url}

Triggered at {timestamp_str} UTC / {local_timestamp_str} Local.
This is an automated message from Argus.
"""

    # Build HTML body
    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff;">
      <h2 style="color: #1e3a8a; margin-top: 0; font-weight: 700; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">Argus Alert Triggered</h2>
      <div style="padding: 15px 0;">
        <p style="font-size: 16px; color: #1e293b; margin: 0 0 10px 0;"><strong>Company:</strong> {company_name} ({symbol})</p>
        <p style="font-size: 16px; color: #1e293b; margin: 0 0 10px 0;"><strong>Alert Name:</strong> {alert_name}</p>
        <p style="font-size: 16px; color: #1e293b; margin: 0 0 10px 0;"><strong>Rule Type:</strong> <code>{rule_type}</code></p>
        <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 12px; margin: 15px 0; border-radius: 4px; line-height: 1.6; font-size: 15px; color: #334155;">
          {html_details}
        </div>
      </div>
      <div style="margin: 25px 0; text-align: center;">
        <a href="{detail_url}" style="background-color: #2563eb; color: #ffffff; padding: 10px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">View Company on Argus</a>
      </div>
      <div style="border-top: 1px solid #e2e8f0; padding-top: 15px; font-size: 12px; color: #64748b; text-align: center;">
        Triggered at {timestamp_str} UTC ({local_timestamp_str} Local) • This is an automated message from Argus.
      </div>
    </div>
    """

    return subject, plain_text_body, html_body
