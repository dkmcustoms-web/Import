"""
sheets_queue.py
Manages the commodity checker queue in Google Sheets.
Uses gspread with a service account JSON (same as Export AI setup).

Sheet columns:
row_id | msg_id | sender_email | subject | received_at |
commodity_code | code_found | ai_verdict | suggested_reply |
status | reply_sent | updated_at
"""

import os
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID       = os.environ.get("COMMODITY_SHEET_ID", "")
WORKSHEET_NAME = "Sheet1"  # default tab name in a new Google Sheet

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COLUMNS = [
    "row_id", "msg_id", "sender_email", "subject", "received_at",
    "commodity_code", "code_found", "ai_verdict", "suggested_reply",
    "status", "reply_sent", "updated_at",
]


class SheetsQueue:
    def __init__(self):
        creds_json = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON", "")
        if not creds_json:
            raise EnvironmentError(
                "GMAIL_SERVICE_ACCOUNT_JSON secret not set. "
                "Add the service account JSON to your Streamlit secrets."
            )
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)

        sh = gc.open_by_key(SHEET_ID)

        # Try to find the worksheet, create it if missing
        try:
            self.ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            self.ws = sh.add_worksheet(
                title=WORKSHEET_NAME, rows=1000, cols=len(COLUMNS)
            )

        # Ensure header row exists
        existing = self.ws.row_values(1)
        if existing != COLUMNS:
            self.ws.insert_row(COLUMNS, index=1)

    # ── Read ────────────────────────────────────────────────────────────────

    def get_all_items(self) -> list[dict]:
        records = self.ws.get_all_records()
        return list(reversed(records))  # newest first

    def msg_id_exists(self, msg_id: str) -> bool:
        col_idx    = COLUMNS.index("msg_id") + 1
        col_values = self.ws.col_values(col_idx)
        return str(msg_id) in col_values

    # ── Write ───────────────────────────────────────────────────────────────

    def add_item(self, item: dict) -> int:
        all_vals = self.ws.col_values(1)  # row_id column (incl. header)
        row_id   = len(all_vals)          # next row_id (header = row 1, so first data = 1)
        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = [
            row_id,
            item.get("msg_id", ""),
            item.get("sender_email", ""),
            item.get("subject", ""),
            item.get("received_at", ""),
            item.get("commodity_code", ""),
            item.get("code_found", ""),
            item.get("ai_verdict", ""),
            item.get("suggested_reply", ""),
            item.get("status", "pending"),
            "",    # reply_sent
            now,   # updated_at
        ]
        self.ws.append_row(row, value_input_option="RAW")
        return row_id

    def update_status(self, row_id: int, status: str, reply_sent: str = ""):
        col_id     = COLUMNS.index("row_id") + 1
        col_values = self.ws.col_values(col_id)

        # Find the row number
        try:
            row_num = col_values.index(str(row_id)) + 1
        except ValueError:
            try:
                row_num = [str(v) for v in col_values].index(str(row_id)) + 1
            except ValueError:
                print(f"[SheetsQueue] row_id {row_id} not found")
                return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ws.update_cell(row_num, COLUMNS.index("status") + 1, status)
        self.ws.update_cell(row_num, COLUMNS.index("updated_at") + 1, now)
        if reply_sent:
            self.ws.update_cell(row_num, COLUMNS.index("reply_sent") + 1, reply_sent)
