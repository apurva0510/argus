import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from argus.core.settings import settings

logger = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    """Check if SMTP variables are set in settings."""
    return bool(settings.email_host and settings.email_to)


def send_email(subject: str, text_content: str, html_content: str | None = None) -> bool:
    """Send an email using SMTP configurations from environment.

    Returns True if successfully sent, False otherwise. Does not crash if SMTP
    is misconfigured or fails.
    """
    if not is_smtp_configured():
        logger.warning(
            "SMTP email delivery is not configured (EMAIL_HOST or EMAIL_TO is empty)."
            " Skipping email delivery."
        )
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.email_from or settings.email_username
        msg["To"] = settings.email_to

        msg.attach(MIMEText(text_content, "plain"))
        if html_content:
            msg.attach(MIMEText(html_content, "html"))

        # Connect to server
        # Port 465 is typical for SSL, others typical for STARTTLS
        if settings.email_port == 465:
            server = smtplib.SMTP_SSL(settings.email_host, settings.email_port, timeout=10)
        else:
            server = smtplib.SMTP(settings.email_host, settings.email_port, timeout=10)
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except Exception:
                logger.exception("STARTTLS initialization failed; aborting email delivery.")
                server.quit()
                return False

        if settings.email_username and settings.email_password:
            server.login(settings.email_username, settings.email_password)

        server.sendmail(msg["From"], [msg["To"]], msg.as_string())
        server.quit()
        logger.info("Email alert successfully sent to %s", settings.email_to)
        return True
    except Exception as e:
        logger.exception("Failed to send email alert via SMTP: %s", str(e))
        return False
