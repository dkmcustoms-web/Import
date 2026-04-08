"""
gmail_sender.py
Sends reply emails via SMTP — same approach as Export AI.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class GmailSender:
    def __init__(self):
        self.host     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.port     = int(os.environ.get("SMTP_PORT", 587))
        self.user     = os.environ.get("SMTP_USER", "dkmcustoms@gmail.com")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.from_    = os.environ.get("SMTP_FROM", "dkmcustoms@gmail.com")
        self.cc       = os.environ.get("COMMODITY_CC", "luc.dekerf@dkm-customs.com")

    def send_reply(self, to: str, subject: str, body: str) -> bool:
        """
        Sends a plain-text reply email.
        Returns True on success, False on failure.
        """
        try:
            msg = MIMEMultipart()
            msg["From"]    = self.from_
            msg["To"]      = to
            msg["Subject"] = subject
            if self.cc:
                msg["Cc"] = self.cc

            msg.attach(MIMEText(body, "plain", "utf-8"))

            recipients = [to]
            if self.cc:
                recipients.append(self.cc)

            with smtplib.SMTP(self.host, self.port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.from_, recipients, msg.as_string())

            return True

        except Exception as e:
            print(f"[GmailSender] SMTP error: {e}")
            return False
