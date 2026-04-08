"""
gmail_reader.py
Polls dkmcustoms@gmail.com via IMAP voor commodity code vragen.
- Pikt emails op met label 'CommodityCheckAI' (ongelezen)
- Verplaatst verwerkte emails naar sublabel 'CommodityCheckAI/Verwerkt'
"""

import os
import imaplib
import email
import re
from datetime import datetime
from email.header import decode_header

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

GMAIL_LABEL           = "CommodityCheckAI"
GMAIL_LABEL_VERWERKT  = "CommodityCheckAI/Verwerkt"
SUBJECT_TAG           = "#commoditycheckAI"


def _decode_str(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _extract_body(msg) -> str:
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


def _ensure_label(mail: imaplib.IMAP4_SSL, label: str) -> bool:
    """Maak label aan als het nog niet bestaat. Returns True als OK."""
    status, _ = mail.select(f'"{label}"')
    if status == "OK":
        return True
    # Aanmaken
    status, _ = mail.create(f'"{label}"')
    return status == "OK"


class GmailReader:
    def __init__(self):
        self.user     = os.environ.get("SMTP_USER", "dkmcustoms@gmail.com")
        self.password = os.environ.get("SMTP_PASSWORD", "")

    def fetch_new_messages(self) -> list[dict]:
        """
        Haalt ongelezen emails op uit label 'CommodityCheckAI'.
        Verplaatst ze naar 'CommodityCheckAI/Verwerkt' na inlezen.
        """
        results = []
        try:
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            mail.login(self.user, self.password)

            # Zorg dat het sublabel bestaat
            _ensure_label(mail, GMAIL_LABEL_VERWERKT)

            # Selecteer het hoofdlabel
            status, _ = mail.select(f'"{GMAIL_LABEL}"')
            if status != "OK":
                # Fallback: inbox, filter op subject
                print(f"[GmailReader] Label niet gevonden, gebruik inbox")
                mail.select("inbox")
                status, data = mail.search(None, f'(UNSEEN SUBJECT "{SUBJECT_TAG}")')
            else:
                status, data = mail.search(None, "UNSEEN")

            if status != "OK" or not data[0]:
                mail.logout()
                return []

            msg_ids = data[0].split()
            print(f"[GmailReader] {len(msg_ids)} nieuwe bericht(en) gevonden")

            for num in msg_ids:
                try:
                    status, msg_data = mail.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    raw     = msg_data[0][1]
                    msg     = email.message_from_bytes(raw)
                    subject = _decode_str(msg.get("Subject", "(no subject)"))
                    from_h  = _decode_str(msg.get("From", ""))
                    date_str= msg.get("Date", "")
                    body    = _extract_body(msg)

                    # Dubbele check op subject tag
                    if SUBJECT_TAG.lower() not in subject.lower():
                        print(f"[GmailReader] Overgeslagen: {subject}")
                        continue

                    # Email adres extraheren
                    match        = re.search(r"[\w.\-+]+@[\w.\-]+", from_h)
                    sender_email = match.group(0) if match else from_h

                    # Datum parsen
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

                    # Verplaats naar sublabel 'CommodityCheckAI/Verwerkt'
                    mail.store(num, "+FLAGS", "\\Seen")
                    mail.copy(num, f'"{GMAIL_LABEL_VERWERKT}"')
                    mail.store(num, "+FLAGS", "\\Deleted")
                    mail.expunge()
                    print(f"[GmailReader] Verwerkt + verplaatst: {subject}")

                except Exception as e:
                    print(f"[GmailReader] Fout bij bericht {num}: {e}")

            mail.logout()

        except Exception as e:
            print(f"[GmailReader] IMAP fout: {e}")

        return results
