"""
gmail_reader.py
Polls dkmcustoms@gmail.com for emails that contain commodity code questions.
Marks processed emails with a label so they aren't re-processed.
"""

import os
import base64
import re
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Label that marks a message as "picked up by Commodity Checker"
PROCESSED_LABEL = "CommodityChecker/Processed"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailReader:
    def __init__(self):
        creds_json = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON")
        if not creds_json:
            raise EnvironmentError("GMAIL_SERVICE_ACCOUNT_JSON secret not set.")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=SCOPES,
            subject=os.environ.get("GMAIL_DELEGATE_ADDRESS", "dkmcustoms@gmail.com"),
        )
        self.service = build("gmail", "v1", credentials=creds)
        self.user_id = "me"
        self._ensure_label()

    # ── Label management ────────────────────────────────────────────────────

    def _ensure_label(self):
        """Create processed label if it doesn't exist yet."""
        try:
            labels = self.service.users().labels().list(userId=self.user_id).execute()
            existing = {l["name"]: l["id"] for l in labels.get("labels", [])}
            if PROCESSED_LABEL in existing:
                self.processed_label_id = existing[PROCESSED_LABEL]
            else:
                created = self.service.users().labels().create(
                    userId=self.user_id,
                    body={"name": PROCESSED_LABEL, "labelListVisibility": "labelShow",
                          "messageListVisibility": "show"},
                ).execute()
                self.processed_label_id = created["id"]
        except HttpError as e:
            print(f"[GmailReader] Label error: {e}")
            self.processed_label_id = None

    def _mark_processed(self, msg_id: str):
        if self.processed_label_id:
            self.service.users().messages().modify(
                userId=self.user_id,
                id=msg_id,
                body={"addLabelIds": [self.processed_label_id]},
            ).execute()

    # ── Fetch new messages ───────────────────────────────────────────────────

    def fetch_new_messages(self) -> list[dict]:
        """
        Returns a list of parsed message dicts for emails NOT yet marked processed.
        Each dict: { msg_id, sender_email, subject, body, received_at }
        """
        query = f"-label:{PROCESSED_LABEL}"
        try:
            result = self.service.users().messages().list(
                userId=self.user_id, q=query, maxResults=50
            ).execute()
        except HttpError as e:
            print(f"[GmailReader] List error: {e}")
            return []

        messages = result.get("messages", [])
        parsed = []
        for m in messages:
            try:
                msg = self.service.users().messages().get(
                    userId=self.user_id, id=m["id"], format="full"
                ).execute()
                parsed_msg = self._parse_message(msg)
                if parsed_msg:
                    parsed.append(parsed_msg)
                    self._mark_processed(m["id"])
            except HttpError as e:
                print(f"[GmailReader] Get error for {m['id']}: {e}")
        return parsed

    # ── Parse ────────────────────────────────────────────────────────────────

    def _parse_message(self, msg: dict) -> dict | None:
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        sender  = headers.get("From", "")
        date_str = headers.get("Date", "")

        # Extract plain text body
        body = self._extract_body(msg["payload"])

        # Only process if email looks like a commodity code question
        if not self._is_commodity_question(subject, body):
            return None

        # Extract sender email address
        email_match = re.search(r"[\w.\-+]+@[\w.\-]+", sender)
        sender_email = email_match.group(0) if email_match else sender

        # Parse date
        try:
            received_at = datetime.strptime(date_str[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            received_at = received_at.strftime("%Y-%m-%d %H:%M")
        except Exception:
            received_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        return {
            "msg_id": msg["id"],
            "sender_email": sender_email,
            "subject": subject,
            "body": body,
            "received_at": received_at,
        }

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain text from message payload."""
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

        parts = payload.get("parts", [])
        for part in parts:
            text = self._extract_body(part)
            if text:
                return text
        return ""

    def _is_commodity_question(self, subject: str, body: str) -> bool:
        """
        Heuristic filter: only process emails that seem to ask about commodity/GN codes.
        Extend these keywords as needed.
        """
        keywords = [
            "commodity code", "gn code", "hs code", "taric", "goederencode",
            "goederennummer", "commodity", "nomenclatuur", "tariff code",
        ]
        combined = (subject + " " + body).lower()
        return any(kw in combined for kw in keywords)
