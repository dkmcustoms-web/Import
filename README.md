# DKM Commodity Checker

Streamlit app that monitors `dkmcustoms@gmail.com` for commodity code validation requests, checks them against the DKM commodity CSV using Claude AI, and lets an operator approve + send replies from a dashboard.

---

## Architecture

```
Gmail inbox
   │  (new email with commodity code question)
   ▼
poller.py  ──────────────────────────────────────────────────────►  Google Sheets Queue
   │  (GmailReader: fetch & label processed)                          (pending / flagged)
   │  (code_validator.py: Claude AI extracts code + validates)             │
   │                                                                       │
   └──────────────────────────────────────────────────────────────         ▼
                                                                    dashboard.py (Streamlit)
                                                                       │  (operator reviews)
                                                                       │  (edits reply)
                                                                       ▼
                                                                    GmailSender → reply email
```

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/dkmcustoms-web/Commodity_Checker.git
cd Commodity_Checker
pip install -r requirements.txt
```

### 2. Add your commodities CSV

Place your CSV file at the project root as `commodities.csv`.
Required columns (names are flexible — the app auto-detects):
- A column with the commodity/GN/HS code (e.g. `code`, `gn_code`, `hs_code`)
- A description column (e.g. `description`, `omschrijving`)
- Optional: `duty_rate`, `vat`, `unit`

### 3. Google Service Account

Use the same service account as Export AI:
`dkm-export-reader@dkm-ai-proxy.iam.gserviceaccount.com`

Enable these APIs in Google Cloud Console:
- Gmail API
- Google Sheets API
- Google Drive API

**Gmail domain-wide delegation** must be enabled for the service account so it can read/send as `dkmcustoms@gmail.com`.
In Google Workspace Admin → Security → API Controls → Domain-wide Delegation, add:
```
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.send
```

### 4. Google Sheet

Create a new Google Sheet and share it with the service account email (Editor access).
Copy the Sheet ID from the URL into your secrets.

### 5. Secrets

Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` and fill in all values.

For Streamlit Cloud: paste the contents under **Settings → Secrets**.

---

## Running

### Dashboard (Streamlit)

```bash
streamlit run dashboard.py
```

### Poller (background process)

Run once:
```bash
python poller.py
```

Run continuously (every 60 seconds):
```bash
python poller.py --loop --interval 60
```

On Railway / Render / a VM: run `poller.py --loop` as a separate background service alongside the Streamlit app.

---

## Email detection logic

Emails are picked up if their subject or body contains any of:
`commodity code`, `gn code`, `hs code`, `taric`, `goederencode`, `goederennummer`, `tariff code`, `nomenclatuur`

Extend the `_is_commodity_question()` method in `gmail_reader.py` to add more keywords.

---

## Status flow

| Status | Meaning |
|--------|---------|
| `pending` | Code found (exact or partial) — awaiting operator approval |
| `flagged` | Code not found or ambiguous — needs manual handling |
| `sent` | Reply approved and sent to client |

---

## DKM Brand

- Sidebar: `#3cceff`
- Primary accent: `#f35e40`
- Font: DM Sans + DM Mono
