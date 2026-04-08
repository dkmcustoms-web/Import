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
    Zoeklogica voor DKM commodity checker:

    1. Exacte match op 10 digits → bevestigd
    2. Geen exacte match → zoek op eerste 8 digits → stel alternatieven voor
    3. Nog steeds niets → not found

    Returns {
        found: bool,
        exact: bool,
        candidates: list[dict],  # alternatieven op 8-digit niveau
        suggested: str,           # meest logische alternatief
        description: str,
    }
    """
    df = _load_commodities()

    code_clean = re.sub(r"\D", "", code).strip()
    if not code_clean:
        return {"found": False, "exact": False, "candidates": [], "suggested": "", "description": ""}

    code_col = "gn_code"
    duty_col = "douanerecht" if "douanerecht" in df.columns else None
    db_codes = df[code_col].fillna("").str.replace(r"\D", "", regex=True)

    # ── Stap 1: Exacte match ─────────────────────────────────────────────
    exact_hits = df[db_codes == code_clean]
    if not exact_hits.empty:
        row = exact_hits.iloc[0]
        return {
            "found":       True,
            "exact":       True,
            "candidates":  [],
            "suggested":   code_clean,
            "duty_rate":   str(row[duty_col]).strip() if duty_col else "",
            "description": "",
        }

    # ── Stap 2: Geen exacte match → zoek op eerste 8 digits ─────────────
    prefix8 = code_clean[:8]
    alt_hits = df[db_codes.str.startswith(prefix8)]

    if not alt_hits.empty:
        candidates = []
        for _, row in alt_hits.iterrows():
            candidates.append({
                "code":      str(row[code_col]).strip(),
                "duty_rate": str(row[duty_col]).strip() if duty_col else "",
            })
        # Deduplicate
        seen = set()
        unique = []
        for c in candidates:
            if c["code"] not in seen:
                seen.add(c["code"])
                unique.append(c)

        # Meest logische suggestie = hoogste suffix (meest specifiek)
        sorted_candidates = sorted(unique, key=lambda x: x["code"], reverse=True)
        suggested = sorted_candidates[0]["code"]

        return {
            "found":       True,
            "exact":       False,
            "candidates":  unique[:10],
            "suggested":   suggested,
            "duty_rate":   sorted_candidates[0]["duty_rate"],
            "description": f"Code {code_clean} niet gevonden. Mogelijke alternatieven op basis van {prefix8}xx: {', '.join([c['code'] for c in unique])}",
        }

    # ── Stap 3: Niets gevonden ───────────────────────────────────────────
    return {"found": False, "exact": False, "candidates": [], "suggested": "", "description": ""}


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
Extract ALL commodity/GN/HS/TARIC codes mentioned in the email below.
Return ONLY the numeric codes, comma-separated (e.g. "3926909790,3926909799").
If no code can be found, return "UNKNOWN".
Include both codes that are being asked about AND codes that are suggested as alternatives.

Subject: {email_subject}
Body:
{email_body[:3000]}
"""
    extract_resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": extract_prompt}],
    )
    raw_codes = extract_resp.content[0].text.strip()
    # Neem de eerste code als primaire, maar geef alle codes mee aan Claude
    all_codes = [c.strip().replace(" ","").replace(".","") for c in raw_codes.split(",") if c.strip()]
    commodity_code = all_codes[0] if all_codes else "UNKNOWN"

    # ── Step 2: Look up ALL codes in CSV ──────────────────────────────────
    all_results = {}
    for code in all_codes:
        all_results[code] = _search_csv(code)
    # Primaire result = eerste code
    csv_result = all_results.get(commodity_code, all_results[list(all_results.keys())[0]])

    # ── Step 3: Build search summary for Claude ─────────────────────────
    candidates_str = ""
    for code, result in all_results.items():
        if result["exact"]:
            candidates_str += f"  - Code {code}: EXACT MATCH ✓ | Duty: {result.get('duty_rate','')}\n"
        elif result["found"]:
            alts = ", ".join([c["code"] for c in result.get("candidates",[])])
            candidates_str += f"  - Code {code}: NOT EXACT — suggested alternative: {result.get('suggested','')} | All alternatives on 8-digit level: {alts}\n"
        else:
            candidates_str += f"  - Code {code}: NOT FOUND in database\n"

    verdict_prompt = f"""
You are a customs expert assistant at DKM Customs (Antwerp, Belgium).
Declarants ask you to verify commodity/GN codes. They propose a code that may be wrong — your job is to confirm or correct it.

Logic:
- If the proposed code is an EXACT MATCH in the database → confirm it
- If the proposed code is NOT found but alternatives exist on the same 8-digit level → suggest the most logical alternative (highest/most specific suffix)
- If nothing is found at all → flag for specialist follow-up

Email subject: {email_subject}
Email body:
{email_body[:2000]}

Database lookup results:
{candidates_str}

Task:
1. Short internal analysis (max 2 sentences). End with: RESOLUTION_TYPE: auto_resolved|existed|not_found

2. Write a SHORT professional reply. There may be multiple questions in one email — handle each one.
   Use EXACTLY this structure:

   Dear Team Member,

   I checked your question and below I provide you with my findings.

   [For each code:]
   • Code proposed: [code]
     [If exact match]: ✓ Confirmed. Duty rate: [rate]. Verify: https://ec.europa.eu/taxation_customs/dds2/taric/
     [If alternative found]: Code [proposed] does not exist. Based on the 8-digit prefix, the most likely correct code is [suggested alternative] (duty: [rate]). Please verify on: https://ec.europa.eu/taxation_customs/dds2/taric/
     [If not found]: Could not be confirmed. A DKM specialist will follow up.

   Kind regards,
   DKM Customs — Commodity Validation Service
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
