"""
sheets_queue.py
Manages the commodity checker queue in Google Sheets.
Sheet columns: row_id | msg_id | sender_email | subject | received_at |
               commodity_code | code_found | ai_verdict | suggested_reply |
               status | reply_sent | updated_at
"""

import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

SHEET_ID = os.environ.get("COMMODITY_SHEET_ID", "")
WORKSHEET_NAME = "Queue"

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
        creds_json = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON")
        if not creds_json:
            raise EnvironmentError("GMAIL_SERVICE_ACCOUNT_JSON not set.")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        try:
            self.ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            self.ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(COLUMNS))
            self.ws.append_row(COLUMNS)

    # ── Read ────────────────────────────────────────────────────────────────

    def get_all_items(self) -> list[dict]:
        records = self.ws.get_all_records()
        return list(reversed(records))  # newest first

    def msg_id_exists(self, msg_id: str) -> bool:
        col_idx = COLUMNS.index("msg_id") + 1
        col_values = self.ws.col_values(col_idx)
        return msg_id in col_values

    # ── Write ───────────────────────────────────────────────────────────────

    def add_item(self, item: dict) -> int:
        """Appends a new row; returns the new row_id."""
        all_vals = self.ws.col_values(1)  # row_id column
        row_id = len(all_vals)  # 1-based, header is row 1, so first data row_id = 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            "",       # reply_sent
            now,      # updated_at
        ]
        self.ws.append_row(row, value_input_option="RAW")
        return row_id

    def update_status(self, row_id: int, status: str, reply_sent: str = ""):
        """Find the row with matching row_id and update status + updated_at."""
        col_id = COLUMNS.index("row_id") + 1
        col_values = self.ws.col_values(col_id)
        try:
            row_num = col_values.index(str(row_id)) + 1
        except ValueError:
            try:
                row_num = col_values.index(row_id) + 1
            except ValueError:
                print(f"[SheetsQueue] row_id {row_id} not found")
                return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_col    = COLUMNS.index("status") + 1
        reply_col     = COLUMNS.index("reply_sent") + 1
        updated_col   = COLUMNS.index("updated_at") + 1

        self.ws.update_cell(row_num, status_col, status)
        self.ws.update_cell(row_num, updated_col, now)
        if reply_sent:
            self.ws.update_cell(row_num, reply_col, reply_sent)
