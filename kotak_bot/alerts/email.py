"""Email alerter (SMTP). Backup to Telegram."""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from loguru import logger


class EmailAlerter:
    def __init__(self, smtp_host: str = "smtp.gmail.com", smtp_port: int = 587,
                 user: str = "", password: str = "", to: str = ""):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.user = user or os.getenv("ALERT_EMAIL_USER", "")
        self.password = password or os.getenv("ALERT_EMAIL_PASSWORD", "")
        self.to = to or os.getenv("ALERT_EMAIL_TO", "")
        self.enabled = bool(self.user and self.password and self.to)
        if not self.enabled:
            logger.warning("EmailAlerter disabled — set ALERT_EMAIL_* env vars")

    def send(self, subject: str, body: str) -> bool:
        if not self.enabled:
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = self.to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.sendmail(self.user, self.to, msg.as_string())
            return True
        except Exception as e:
            logger.warning(f"Email send failed: {e}")
            return False
