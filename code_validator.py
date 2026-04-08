"""
code_validator.py
Validates commodity codes against the DKM commodities CSV using Claude AI.
Returns a structured verdict for each incoming email.
"""

import os
import re
import anthropic
import pandas as pd

CLAUDE_MODEL = "claude-opus-4-5"


def _load_commodities() -> pd.DataFrame:
    """
    Laad taric_clean.csv — UTF-8, puntkomma-separator.
    Kolommen: gn_code | douanerecht | type_duty
    """
    csv_path = os.environ.get("COMMODITIES_CSV_PATH", "taric_clean.csv")
    print(f"[Validator] Laden van: {csv_path}")
    import os as _os; print(f"[Validator] Bestand bestaat: {_os.path.exists(csv_path)}, CWD: {_os.getcwd()}")
    df = pd.read_csv(csv_path, dtype=str, sep=";", encoding="utf-8")
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.fillna("")
    print(f"[Validator] CSV geladen: {len(df)} rijen, kolommen: {list(df.columns)}")
    return df


def _search_csv(code: str) -> dict:
    """
    Zoekt een GN-code op in de DKM commodities CSV.
    Kolommen: gn_code | omschrijving | douanerecht | code_niveau | hoofdstuk | afdeling
    Returns { found: bool, exact: bool, candidates: list[dict], description: str }
    """
    df = _load_commodities()

    # Enkel cijfers van de gezochte code
    code_clean = re.sub(r"\D", "", code)
    if not code_clean:
        return {"found": False, "exact": False, "candidates": [], "description": ""}

    # Kolommen van taric_clean.csv
    code_col = "gn_code"
    duty_col = "douanerecht" if "douanerecht" in df.columns else None
    desc_col = None  # geen omschrijving in TARIC CSV

    # Zoek: gn_code begint met de gezochte digits
    mask = (
        df[code_col]
        .fillna("")
        .str.replace(r"\D", "", regex=True)
        .str.startswith(code_clean)
    )
    hits = df[mask].copy()

    if hits.empty:
        return {"found": False, "exact": False, "candidates": [], "description": ""}

    candidates = []
    for _, row in hits.iterrows():
        entry = {
            "code":        str(row[code_col]).strip(),
            "description": str(row[desc_col]).strip() if desc_col else "",
            "duty_rate":   str(row[duty_col]).strip() if duty_col else "",
            "niveau":      str(row.get("code_niveau", "")).strip(),
        }
        candidates.append(entry)

    # Exacte match = gn_code is exact gelijk aan gezochte code
    exact_match = any(
        re.sub(r"\D", "", c["code"]) == code_clean
        for c in candidates
    )

    return {
        "found":       True,
        "exact":       exact_match,
        "candidates":  candidates[:5],
        "description": candidates[0]["description"] if candidates else "",
    }


def validate(email_body: str, email_subject: str) -> dict:
    """
    Main entry point.
    Returns:
    {
      commodity_code: str,
      code_found: "true" | "false" | "ambiguous",
      ai_verdict: str,
      suggested_reply: str,
    }
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ── Step 1: Extract the commodity code from the email ──────────────────
    extract_prompt = f"""
You are a customs expert assistant at DKM Customs (Antwerp).
Extract the commodity/GN/HS/TARIC code being asked about from the email below.
Return ONLY the numeric code string, nothing else. If multiple codes are mentioned, return the primary one.
If no code can be found, return "UNKNOWN".

Subject: {email_subject}
Body:
{email_body[:3000]}
"""
    extract_resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=64,
        messages=[{"role": "user", "content": extract_prompt}],
    )
    commodity_code = extract_resp.content[0].text.strip().replace(" ", "").replace(".", "")

    # ── Step 2: Look up in CSV ──────────────────────────────────────────────
    csv_result = _search_csv(commodity_code)

    # ── Step 3: Ask Claude to write verdict + reply ─────────────────────────
    candidates_str = ""
    if csv_result["found"]:
        for c in csv_result["candidates"]:
            candidates_str += f"  - Code: {c['code']} | {c['description']}"
            if c.get("duty_rate"):
                candidates_str += f" | Duty: {c['duty_rate']}"
            candidates_str += "\n"
    else:
        candidates_str = "  (no match found in DKM commodity database)"

    verdict_prompt = f"""
You are a customs expert assistant at DKM Customs (Antwerp, Belgium).
A client sent an email asking about one or more commodity/GN codes.

Email subject: {email_subject}
Email body:
{email_body[:2000]}

Code(s) found in email: {commodity_code}

Search result from DKM commodity database:
{candidates_str}
Exact match: {csv_result.get('exact', False)}

Task:
1. Write a short internal analysis (max 2 sentences) — was the code found, correct, ambiguous?
   Also state the resolution type: "auto_resolved" (code found + confirmed), "existed" (code found but not exact), "not_found" (code not in database).

2. Write a SHORT professional reply email. Note: there may be multiple questions in one email — answer all of them.
   Use EXACTLY this structure:

   Dear [name or "Team Member"],

   I checked your question and below I provide you with my findings.

   [For each code asked:]
   - Code: [code]
   - [If found]: Confirmed. Description: [description]. Duty rate: [duty rate if available]. You can verify this on the EU TARIC website: https://ec.europa.eu/taxation_customs/dds2/taric/
   - [If not found]: This code could not be confirmed in our database. A DKM specialist will follow up.

   Kind regards,
   DKM Customs — Commodity Validation Service

Return your response in this exact format:
ANALYSIS: <2 sentences max. End with RESOLUTION_TYPE: auto_resolved|existed|not_found>
REPLY:
<reply email text>
"""
    verdict_resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": verdict_prompt}],
    )
    raw = verdict_resp.content[0].text.strip()

    # Parse
    analysis = ""
    reply_body = ""
    if "ANALYSIS:" in raw and "REPLY:" in raw:
        analysis_part = raw.split("ANALYSIS:")[1].split("REPLY:")[0].strip()
        reply_part    = raw.split("REPLY:")[1].strip()
        analysis = analysis_part
        reply_body = reply_part
    else:
        analysis = raw[:300]
        reply_body = raw

    # Determine code_found flag
    if not csv_result["found"]:
        code_found = "false"
    elif csv_result["exact"]:
        code_found = "true"
    else:
        code_found = "ambiguous"

    # Extract resolution_type from analysis
    resolution_type = "not_found"
    if "auto_resolved" in analysis.lower():
        resolution_type = "auto_resolved"
    elif "existed" in analysis.lower():
        resolution_type = "existed"
    elif code_found == "true":
        resolution_type = "auto_resolved"
    elif code_found == "ambiguous":
        resolution_type = "existed"

    return {
        "commodity_code": commodity_code,
        "code_found":     code_found,
        "ai_verdict":     analysis,
        "suggested_reply": reply_body,
        "resolution_type": resolution_type,
    }
