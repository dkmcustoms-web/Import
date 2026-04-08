"""
poller.py
Background process: polls Gmail, validates codes, pushes to Google Sheets queue.
Run this separately (e.g. via a scheduler or a second Streamlit thread).

Usage:
    python poller.py            # runs once
    python poller.py --loop     # runs every 60 seconds
"""

import sys
import time
import argparse
from gmail_reader import GmailReader
from code_validator import validate
from sheets_queue import SheetsQueue


def poll_once(reader: GmailReader, queue: SheetsQueue):
    print("[Poller] Fetching new messages…")
    messages = reader.fetch_new_messages()
    print(f"[Poller] Found {len(messages)} new message(s).")

    for msg in messages:
        msg_id = msg["msg_id"]

        # Deduplicate
        if queue.msg_id_exists(msg_id):
            print(f"[Poller] Skipping already-queued msg {msg_id}")
            continue

        print(f"[Poller] Validating: {msg['subject']}")
        try:
            result = validate(msg["body"], msg["subject"])
        except Exception as e:
            print(f"[Poller] Validation error: {e}")
            result = {
                "commodity_code": "ERROR",
                "code_found": "false",
                "ai_verdict": f"Validation failed: {e}",
                "suggested_reply": "Er is een fout opgetreden bij de automatische validatie. Een specialist neemt contact op.",
            }

        # Determine initial status
        if result["code_found"] == "false":
            status = "flagged"
        else:
            status = "pending"

        item = {
            **msg,
            **result,
            "status": status,
        }
        row_id = queue.add_item(item)
        print(f"[Poller] Added to queue → row_id={row_id}, status={status}, code={result['commodity_code']}, found={result['code_found']}")


def main():
    parser = argparse.ArgumentParser(description="DKM Commodity Checker Poller")
    parser.add_argument("--loop", action="store_true", help="Run in continuous loop")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default: 60)")
    args = parser.parse_args()

    reader = GmailReader()
    queue  = SheetsQueue()

    if args.loop:
        print(f"[Poller] Starting loop (interval: {args.interval}s). Press Ctrl+C to stop.")
        while True:
            try:
                poll_once(reader, queue)
            except Exception as e:
                print(f"[Poller] Error in loop: {e}")
            time.sleep(args.interval)
    else:
        poll_once(reader, queue)


if __name__ == "__main__":
    main()
