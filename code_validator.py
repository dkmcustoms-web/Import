"""
code_validator.py
Validates commodity codes against the DKM commodities CSV using Claude AI.
Returns a structured verdict for each incoming email.
"""

import os
import re
import anthropic
import pandas as pd
from functools import lru_cache

CLAUDE_MODEL = "claude-opus-4-5"


@lru_cache(maxsize=1)
def _load_commodities() -> pd.DataFrame:
    """Load commodities CSV once and cache it."""
    csv_path = os.environ.get("COMMODITIES_CSV_PATH", "commodities.csv")
    df = pd.read_csv(csv_path, dtype=str)
    # Normalise column names to lowercase
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _search_csv(code: str) -> dict:
    """
    Look up a commodity code in the CSV.
    Returns { found: bool, exact: bool, candidates: list[dict], description: str }
    """
    df = _load_commodities()

    code_clean = re.sub(r"\D", "", code)  # digits only

    # Determine which column holds the code
    code_cols = [c for c in df.columns if any(k in c for k in ["code", "gn", "hs", "commodity", "tariff"])]
    if not code_cols:
        code_cols = [df.columns[0]]  # fallback to first column

    results = []
    for col in code_cols:
        mask = df[col].str.replace(r"\D", "", regex=True).str.startswith(code_clean)
        hits = df[mask]
        if not hits.empty:
            results.append(hits)

    if not results:
        return {"found": False, "exact": False, "candidates": [], "description": ""}

    combined = pd.concat(results).drop_duplicates()

    # Description column heuristic
    desc_cols = [c for c in df.columns if any(k in c for k in ["desc", "omschr", "name", "text", "label"])]
    desc_col = desc_cols[0] if desc_cols else (df.columns[1] if len(df.columns) > 1 else None)

    candidates = []
    for _, row in combined.iterrows():
        entry = {}
        for col in code_cols:
            entry["code"] = row[col]
        entry["description"] = row[desc_col] if desc_col else ""
        # Extra fields (duty rate etc.)
        for extra in ["duty_rate", "vat", "unit"]:
            if extra in df.columns:
                entry[extra] = row[extra]
        candidates.append(entry)

    exact_code_clean = code_clean.ljust(8, "0")[:8]
    exact_match = any(
        re.sub(r"\D", "", c.get("code", ""))[:8] == exact_code_clean
        for c in candidates
    )

    description = candidates[0]["description"] if candidates else ""
    return {
        "found": True,
        "exact": exact_match,
        "candidates": candidates[:5],
        "description": description,
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
A client sent an email asking about a commodity/GN code.

Email subject: {email_subject}
Email body:
{email_body[:2000]}

The code they asked about: {commodity_code}

Search result from DKM commodity database:
{candidates_str}
Exact match: {csv_result.get('exact', False)}

Task:
1. Write a short internal analysis (2-3 sentences) of whether the code is correct.
2. Write a professional reply email to the client (in the same language they used — Dutch or English).
   - If the code is correct: confirm it, give the description, mention any duty rate if available.
   - If the code is wrong/not found: say it could not be confirmed and that a DKM specialist will follow up.
   - Always sign off as: "DKM Customs — Commodity Validation Service"
   - Keep it concise and professional.

Return your response in this exact format:
ANALYSIS: <your 2-3 sentence internal analysis>
REPLY:
<full reply email text>
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

    return {
        "commodity_code": commodity_code,
        "code_found": code_found,
        "ai_verdict": analysis,
        "suggested_reply": reply_body,
    }
