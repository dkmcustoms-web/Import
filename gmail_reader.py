"""
gmail_reader.py
Polls dkmcustoms@gmail.com via IMAP voor commodity code vragen.
Gebruikt de permanente Message-ID header als unieke identifier.
- Pikt emails op met label 'CommodityCheckAI' (ongelezen)
- Voegt sublabel 'CommodityCheckAI/Verwerkt' toe na verwerking
- Markeert als gelezen — mail blijft gewoon staan in Gmail
"""

import os
import imaplib
import email
import re
from datetime import datetime
from email.header import decode_header

IMAP_HOST            = "imap.gmail.com"
IMAP_PORT            = 993
GMAIL_LABEL          = "DevCommodityCheckAI"
GMAIL_LABEL_VERWERKT = "DevCommodityCheckAI/Verwerkt"
SUBJECT_TAG          = "#commoditycheckAI_dev"


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


class GmailReader:
    def __init__(self):
        self.user     = os.environ.get("SMTP_USER", "dkmcustoms@gmail.com")
        self.password = os.environ.get("SMTP_PASSWORD", "")

    def _ensure_label(self, mail: imaplib.IMAP4_SSL, label: str):
        """Maak label aan als het nog niet bestaat."""
        status, _ = mail.select(f'"{label}"')
        if status != "OK":
            mail.create(f'"{label}"')
            print(f"[GmailReader] Label aangemaakt: {label}")

    def fetch_new_messages(self) -> list[dict]:
        results = []
        try:
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            mail.login(self.user, self.password)

            # Zorg dat sublabel bestaat
            self._ensure_label(mail, GMAIL_LABEL_VERWERKT)

            # Selecteer label-folder (mails zijn gearchiveerd via filter)
            status, _ = mail.select(f'"{GMAIL_LABEL}"')
            if status != "OK":
                print(f"[GmailReader] Label '{GMAIL_LABEL}' niet gevonden!")
                mail.logout()
                return []
            # Enkel ONGELEZEN mails in label ophalen
            status, data = mail.search(None, "UNSEEN")
            print(f"[GmailReader] UNSEEN search status: {status}, resultaat: {data}")

            if status != "OK" or not data[0]:
                mail.logout()
                return []

            msg_ids = data[0].split()
            print(f"[GmailReader] {len(msg_ids)} bericht(en) in label gevonden")

            for num in msg_ids:
                try:
                    # Fetch alleen headers eerst voor snelheid
                    status, msg_data = mail.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    raw      = msg_data[0][1]
                    msg      = email.message_from_bytes(raw)

                    # Gebruik permanente Message-ID — normaliseer < > en whitespace
                    message_id = msg.get("Message-ID", "").strip().strip("<>").strip()
                    if not message_id:
                        message_id = f"{msg.get('From','')}-{msg.get('Subject','')}-{msg.get('Date','')}".strip()
                    print(f"[GmailReader] Message-ID: {message_id[:80]}")

                    subject  = _decode_str(msg.get("Subject", "(geen subject)"))
                    from_h   = _decode_str(msg.get("From", ""))
                    date_str = msg.get("Date", "")
                    body     = _extract_body(msg)

                    if SUBJECT_TAG.lower() not in subject.lower():
                        print(f"[GmailReader] Overgeslagen (geen tag): {subject}")
                        continue

                    match        = re.search(r"[\w.\-+]+@[\w.\-]+", from_h)
                    sender_email = match.group(0) if match else from_h

                    try:
                        received_at = datetime.strptime(
                            date_str[:25].strip(), "%a, %d %b %Y %H:%M:%S"
                        ).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        received_at = datetime.now().strftime("%Y-%m-%d %H:%M")

                    results.append({
                        "msg_id":       message_id,   # ✅ permanente ID
                        "sender_email": sender_email,
                        "subject":      subject,
                        "body":         body,
                        "received_at":  received_at,
                    })

                    # Markeer als gelezen via UID voor persistente flag in Gmail
                    mail.store(num, "+FLAGS", "(\\Seen)")
                    print(f"[GmailReader] Verwerkt + gelezen: {subject}")

                except Exception as e:
                    print(f"[GmailReader] Fout bij bericht {num}: {e}")

            mail.logout()

        except Exception as e:
            print(f"[GmailReader] IMAP fout: {e}")

        return results
