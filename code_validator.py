"""
code_validator.py
Validates commodity codes against the DKM TARIC CSV.
Steps:
  1. Extract codes from email (Claude)
  2. Check LearnedCodes cache → instant reply if found
  3. Look up in TARIC CSV (exact match + 8-digit fallback)
  4. Get goods description (Claude, max 15 words)
  5. Build reply programmatically from CSV data only
  6. Return full result with decision log
"""

import os
import re
import anthropic
import pandas as pd

CLAUDE_MODEL = "claude-sonnet-4-5"


def _load_commodities() -> pd.DataFrame:
    csv_path = os.environ.get("COMMODITIES_CSV_PATH", "taric_clean.csv")
    print(f"[Validator] Loading CSV: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str, sep=";", encoding="utf-8")
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.fillna("")
    print(f"[Validator] CSV loaded: {len(df)} rows, columns: {list(df.columns)}")
    return df


def _search_code(code: str) -> dict:
    """
    Step 1: exact match on full code
    Step 2: if not found, search on first 8 digits and suggest best alternative
    Step 3: not found at all
    """
    df       = _load_commodities()
    code_clean = re.sub(r"\D", "", code).strip()
    if not code_clean:
        return {"found": False, "exact": False, "suggested": "", "duty_rate": "", "alternatives": [], "log": f"Code '{code}' contains no digits."}

    code_col = "gn_code"
    duty_col = "douanerecht" if "douanerecht" in df.columns else None
    db_codes = df[code_col].fillna("").str.replace(r"\D", "", regex=True)

    # Step 1: exact match
    exact_hits = df[db_codes == code_clean]
    if not exact_hits.empty:
        duty = str(exact_hits.iloc[0][duty_col]).strip() if duty_col else ""
        log  = f"Code {code_clean}: EXACT MATCH found in TARIC database. Duty rate: {duty}."
        print(f"[Validator] {log}")
        return {"found": True, "exact": True, "suggested": code_clean, "duty_rate": duty, "alternatives": [], "log": log}

    # Step 2: 8-digit prefix fallback
    prefix8  = code_clean[:8]
    alt_hits = df[db_codes.str.startswith(prefix8)]
    if not alt_hits.empty:
        seen, alternatives = set(), []
        for _, row in alt_hits.iterrows():
            c = str(row[code_col]).strip()
            if c not in seen:
                seen.add(c)
                alternatives.append({"code": c, "duty_rate": str(row[duty_col]).strip() if duty_col else ""})
        alts_sorted = sorted(alternatives, key=lambda x: x["code"], reverse=True)
        suggested   = alts_sorted[0]["code"]
        duty        = alts_sorted[0]["duty_rate"]
        alt_codes   = [a["code"] for a in alternatives]
        log = (f"Code {code_clean}: NOT FOUND in TARIC database. "
               f"Searched on 8-digit prefix '{prefix8}xx'. "
               f"Found {len(alternatives)} alternative(s): {', '.join(alt_codes)}. "
               f"Best suggestion: {suggested} (duty: {duty}).")
        print(f"[Validator] {log}")
        return {"found": True, "exact": False, "suggested": suggested, "duty_rate": duty, "alternatives": alt_codes, "log": log}

    # Step 3: not found
    log = f"Code {code_clean}: NOT FOUND in TARIC database. No alternatives found on prefix '{code_clean[:8]}'."
    print(f"[Validator] {log}")
    return {"found": False, "exact": False, "suggested": "", "duty_rate": "", "alternatives": [], "log": log}


def validate(email_body: str, email_subject: str, learned_codes: dict = None) -> dict:
    """
    Main validation function.
    learned_codes: dict {code: {confirmed_code, duty_rate, times_seen, ...}} for cache lookup.
    Returns full result including decision_log for transparency.
    """
    client       = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    decision_log = []

    # ── Step 1: Extract codes from email ──────────────────────────────────────
    decision_log.append("STEP 1: Extracting commodity codes from email.")
    extract_resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": f"""
Extract ALL commodity/GN/HS codes mentioned in this email.
Return ONLY the numeric codes, comma-separated (e.g. "3926909790,3926909799").
Include both proposed codes AND alternative codes mentioned.
If no code found, return "UNKNOWN".

Subject: {email_subject}
Body: {email_body[:2000]}
"""}],
    )
    raw_codes  = extract_resp.content[0].text.strip()
    all_codes  = [re.sub(r"\D", "", c).strip() for c in raw_codes.split(",") if re.sub(r"\D", "", c).strip()]
    if not all_codes or all_codes == ["UNKNOWN"]:
        all_codes = ["UNKNOWN"]
    primary_code = all_codes[0]
    decision_log.append(f"Codes found in email: {', '.join(all_codes)}.")
    print(f"[Validator] Codes found: {all_codes}")

    # ── Step 2: Check LearnedCodes cache ──────────────────────────────────────
    decision_log.append("STEP 2: Checking LearnedCodes cache.")
    if learned_codes and all_codes != ["UNKNOWN"]:
        cached_hits = {code: learned_codes[code] for code in all_codes if code in learned_codes}
        if cached_hits and len(cached_hits) == len(all_codes):
            decision_log.append(f"CACHE HIT: All codes found in LearnedCodes database: {list(cached_hits.keys())}. No TARIC lookup needed.")
            bullets = []
            for code, info in cached_hits.items():
                times = info.get("times_seen", 1)
                duty  = info.get("duty_rate", "")
                conf  = info.get("confirmed_code", code)
                bullets.append(
                    f"\u2022 {conf}  \u2014  Confirmed (previously validated {times}x)"
                    + (f"  \u2014  Third country tariff: {duty}" if duty else "")
                )
            reply = (
                "Dear Team Member,\n\n"
                "I checked your question and below I provide you with my findings.\n\n"
                + "\n".join(bullets)
                + "\n\n---\n"
                f"Decision log: {' | '.join(decision_log)}\n\n"
                "Kind regards,\nDKM Customs \u2014 Commodity Validation Service"
            )
            return {
                "commodity_code":  primary_code,
                "confirmed_code":  cached_hits.get(primary_code, {}).get("confirmed_code", primary_code),
                "code_found":      "true",
                "ai_verdict":      f"Cache hit. {' '.join(decision_log)} RESOLUTION_TYPE: auto_resolved",
                "suggested_reply": reply,
                "resolution_type": "auto_resolved",
                "from_cache":      True,
                "decision_log":    " | ".join(decision_log),
            }
        elif cached_hits:
            decision_log.append(f"Partial cache hit for: {list(cached_hits.keys())}. Continuing with TARIC lookup for remaining codes.")
        else:
            decision_log.append("No cache hits. Proceeding with TARIC database lookup.")
    else:
        decision_log.append("No LearnedCodes cache available or no valid codes. Proceeding with TARIC lookup.")

    # ── Step 3: Look up all codes in TARIC CSV ────────────────────────────────
    decision_log.append("STEP 3: Looking up codes in TARIC CSV database.")
    all_results = {}
    for code in all_codes:
        if code == "UNKNOWN":
            all_results[code] = {"found": False, "exact": False, "suggested": "", "duty_rate": "", "alternatives": [], "log": "No code found in email."}
        else:
            all_results[code] = _search_code(code)
        decision_log.append(all_results[code]["log"])

    csv_result = all_results.get(primary_code, list(all_results.values())[0])

    # ── Step 4: Get goods descriptions (Claude, descriptions only) ────────────
    decision_log.append("STEP 4: Retrieving goods descriptions.")
    codes_for_desc = {}
    for code, result in all_results.items():
        if result["exact"]:
            codes_for_desc[code] = code
        elif result["found"]:
            codes_for_desc[code] = result.get("suggested", code)

    descriptions = {}
    if codes_for_desc:
        desc_list = "\n".join([f"- {c}" for c in set(codes_for_desc.values())])
        try:
            desc_resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": f"""
For each TARIC/GN code below, provide a clear goods description (max 15 words).
Return ONLY in this exact format, one per line:
CODE: description

Codes:
{desc_list}
"""}],
            )
            for line in desc_resp.content[0].text.strip().split("\n"):
                if ":" in line:
                    parts = line.split(":", 1)
                    descriptions[parts[0].strip()] = parts[1].strip()
            decision_log.append(f"Descriptions retrieved for: {list(descriptions.keys())}.")
        except Exception as e:
            decision_log.append(f"Description lookup failed: {e}.")
            print(f"[Validator] Description error: {e}")

    # ── Step 5: Build reply programmatically ──────────────────────────────────
    decision_log.append("STEP 5: Building reply from TARIC data only.")
    bullets        = []
    analysis_lines = []
    any_not_found  = False

    for code, result in all_results.items():
        if result["exact"]:
            duty = result.get("duty_rate", "")
            desc = descriptions.get(code, "")
            bullets.append(
                f"\u2022 {code}  \u2014  Confirmed"
                + (f"  \u2014  {desc}" if desc else "")
                + (f"  \u2014  Third country tariff: {duty}" if duty else "")
            )
            analysis_lines.append(f"Code {code}: exact match in TARIC database.")
        elif result["found"]:
            suggested = result.get("suggested", "")
            duty      = result.get("duty_rate", "")
            desc      = descriptions.get(suggested, "")
            bullets.append(
                f"\u2022 {suggested}  \u2014  Suggested, code existed"
                + (f"  \u2014  {desc}" if desc else "")
                + (f"  \u2014  Third country tariff: {duty}" if duty else "")
            )
            analysis_lines.append(
                f"Code {code} does not exist. Closest match: {suggested}"
                + (f" (duty: {duty})" if duty else "") + "."
            )
        else:
            bullets.append(f"\u2022 {code}  \u2014  Not found in TARIC database.")
            analysis_lines.append(f"Code {code}: not found in TARIC database.")
            any_not_found = True

    # Determine resolution type
    if not csv_result["found"]:
        code_found      = "false"
        resolution_type = "not_found"
    elif csv_result["exact"]:
        code_found      = "true"
        resolution_type = "auto_resolved"
    else:
        any_found       = any(r["found"] for r in all_results.values())
        code_found      = "ambiguous" if any_found else "false"
        resolution_type = "existed"   if any_found else "not_found"

    follow_up = "\nA DKM specialist will follow up for codes that could not be confirmed." if any_not_found else ""
    analysis  = " ".join(analysis_lines) + f" RESOLUTION_TYPE: {resolution_type}"
    decision_log.append(f"Final resolution: {resolution_type}.")

    reply_body = (
        "Dear Team Member,\n\n"
        "I checked your question and below I provide you with my findings.\n\n"
        + "\n".join(bullets)
        + follow_up
        + "\n\n---\n"
        f"AI Analysis: {analysis}\n\n"
        "Kind regards,\nDKM Customs \u2014 Commodity Validation Service"
    )

    # Confirmed code
    if csv_result["exact"]:
        confirmed_code = primary_code
    elif csv_result["found"]:
        confirmed_code = csv_result.get("suggested", "")
    else:
        confirmed_code = ""

    return {
        "commodity_code":  primary_code,
        "confirmed_code":  confirmed_code,
        "code_found":      code_found,
        "ai_verdict":      analysis,
        "suggested_reply": reply_body,
        "resolution_type": resolution_type,
        "from_cache":      False,
        "decision_log":    " | ".join(decision_log),
    }
