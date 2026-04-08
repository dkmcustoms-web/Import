"""
gmail_reader.py
Polls dkmcustoms@gmail.com via IMAP for commodity code questions.
Marks processed emails as READ so they aren't re-processed.
"""

import os
import imaplib
import email
import re
from datetime import datetime
from email.header import decode_header

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

KEYWORDS = [
    "commodity code", "gn code", "hs code", "taric", "goederencode",
    "goederennummer", "commodity", "nomenclatuur", "tariff code",
]


def _decode_str(value: str) -> str:
    """Decode encoded email header strings."""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _extract_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="ignore")
                break
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="ignore")
    return body


def _is_commodity_question(subject: str, body: str) -> bool:
    combined = (subject + " " + body).lower()
    return any(kw in combined for kw in KEYWORDS)


class GmailReader:
    def __init__(self):
        self.user     = os.environ.get("SMTP_USER", "dkmcustoms@gmail.com")
        self.password = os.environ.get("SMTP_PASSWORD", "")

    def fetch_new_messages(self) -> list[dict]:
        """
        Connects via IMAP, fetches UNSEEN emails that look like commodity questions.
        Marks them as SEEN after reading.
        Returns list of dicts: { msg_id, sender_email, subject, body, received_at }
        """
        results = []
        try:
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            mail.login(self.user, self.password)
            mail.select("inbox")

            # Search for unread messages
            status, data = mail.search(None, "UNSEEN")
            if status != "OK":
                return []

            msg_ids = data[0].split()
            for num in msg_ids:
                try:
                    status, msg_data = mail.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    subject     = _decode_str(msg.get("Subject", "(no subject)"))
                    from_header = _decode_str(msg.get("From", ""))
                    date_str    = msg.get("Date", "")
                    body        = _extract_body(msg)

                    # Only process commodity questions
                    if not _is_commodity_question(subject, body):
                        continue

                    # Extract email address
                    email_match = re.search(r"[\w.\-+]+@[\w.\-]+", from_header)
                    sender_email = email_match.group(0) if email_match else from_header

                    # Parse date
                    try:
                        received_at = datetime.strptime(
                            date_str[:25].strip(), "%a, %d %b %Y %H:%M:%S"
                        ).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        received_at = datetime.now().strftime("%Y-%m-%d %H:%M")

                    results.append({
                        "msg_id":       num.decode(),
                        "sender_email": sender_email,
                        "subject":      subject,
                        "body":         body,
                        "received_at":  received_at,
                    })

                    # Mark as read so we don't re-process
                    mail.store(num, "+FLAGS", "\\Seen")

                except Exception as e:
                    print(f"[GmailReader] Error reading message {num}: {e}")

            mail.logout()

        except Exception as e:
            print(f"[GmailReader] IMAP error: {e}")

        return results
