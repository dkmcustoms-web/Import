"""
gmail_sender.py
Sends reply emails via the dkmcustoms@gmail.com service account.
"""

import os
import base64
import json
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

FROM_ADDRESS = "dkmcustoms@gmail.com"
CC_ADDRESS   = os.environ.get("COMMODITY_CC", "luc.dekerf@dkm-customs.com")


class GmailSender:
    def __init__(self):
        creds_json = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON")
        if not creds_json:
            raise EnvironmentError("GMAIL_SERVICE_ACCOUNT_JSON not set.")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=SCOPES,
            subject=os.environ.get("GMAIL_DELEGATE_ADDRESS", FROM_ADDRESS),
        )
        self.service = build("gmail", "v1", credentials=creds)

    def send_reply(self, to: str, subject: str, body: str) -> bool:
        """
        Sends an email reply.
        Returns True on success, False on failure.
        """
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["To"]      = to
            msg["From"]    = FROM_ADDRESS
            msg["Subject"] = subject
            if CC_ADDRESS:
                msg["Cc"] = CC_ADDRESS

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            self.service.users().messages().send(
                userId="me",
                body={"raw": raw},
            ).execute()
            return True
        except HttpError as e:
            print(f"[GmailSender] Send error: {e}")
            return False
