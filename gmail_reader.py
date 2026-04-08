"""
gmail_reader.py
Polls dkmcustoms@gmail.com via IMAP voor commodity code vragen.
Detectie via Gmail label 'CommodityCheckAI' (aangemaakt door Gmail filter op #commoditycheckAI).
Markeert verwerkte emails als SEEN zodat ze niet opnieuw worden opgepikt.
"""

import os
import imaplib
import email
import re
from datetime import datetime
from email.header import decode_header

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Gmail label toegevoegd door de Gmail filter
GMAIL_LABEL = "CommodityCheckAI"

# Verplichte tag in het subject (dubbele check)
SUBJECT_TAG = "#commoditycheckAI"


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

    def fetch_new_messages(self) -> list[dict]:
        """
        Haalt ongelezen emails op uit het Gmail label 'CommodityCheckAI'.
        Fallback: zoekt in inbox op subject tag als label niet bestaat.
        Markeert emails als SEEN na verwerking.
        """
        results = []
        try:
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            mail.login(self.user, self.password)

            # Probeer eerst het label als IMAP folder te selecteren
            status, _ = mail.select(f'"{GMAIL_LABEL}"')
            if status != "OK":
                print(f"[GmailReader] Label '{GMAIL_LABEL}' niet gevonden, gebruik inbox fallback")
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

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    subject     = _decode_str(msg.get("Subject", "(no subject)"))
                    from_header = _decode_str(msg.get("From", ""))
                    date_str    = msg.get("Date", "")
                    body        = _extract_body(msg)

                    # Dubbele check: subject moet de tag bevatten
                    if SUBJECT_TAG.lower() not in subject.lower():
                        print(f"[GmailReader] Overgeslagen (geen tag in subject): {subject}")
                        continue

                    # Email adres extraheren
                    email_match  = re.search(r"[\w.\-+]+@[\w.\-]+", from_header)
                    sender_email = email_match.group(0) if email_match else from_header

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

                    # Markeer als gelezen — niet opnieuw verwerken
                    mail.store(num, "+FLAGS", "\\Seen")
                    print(f"[GmailReader] Verwerkt: {subject} van {sender_email}")

                except Exception as e:
                    print(f"[GmailReader] Fout bij bericht {num}: {e}")

            mail.logout()

        except Exception as e:
            print(f"[GmailReader] IMAP fout: {e}")

        return results
