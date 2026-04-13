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
import json
import anthropic
import pandas as pd

CLAUDE_MODEL = "claude-sonnet-4-5"


def _load_commodities() -> pd.DataFrame:
    csv_path = os.environ.get("COMMODITIES_CSV_PATH", "commodity10digits_clean.csv")
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

    desc_col  = "short_description" if "short_description" in df.columns else None

    # Step 1: exact match
    exact_hits = df[db_codes == code_clean]
    if not exact_hits.empty:
        duty = str(exact_hits.iloc[0][duty_col]).strip() if duty_col else ""
        desc = str(exact_hits.iloc[0][desc_col]).strip() if desc_col else ""
        log  = f"Code {code_clean}: EXACT MATCH found in TARIC database. Duty rate: {duty}."
        print(f"[Validator] {log}")
        return {"found": True, "exact": True, "suggested": code_clean, "duty_rate": duty, "description": desc, "alternatives": [], "log": log}

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
        # Get description for suggested code
        sugg_hits = df[db_codes == re.sub(r"\D", "", suggested)]
        desc = str(sugg_hits.iloc[0][desc_col]).strip() if desc_col and not sugg_hits.empty else ""
        log = (f"Code {code_clean}: NOT FOUND in TARIC database. "
               f"Searched on 8-digit prefix '{prefix8}xx'. "
               f"Found {len(alternatives)} alternative(s): {', '.join(alt_codes)}. "
               f"Best suggestion: {suggested} (duty: {duty}).")
        print(f"[Validator] {log}")
        return {"found": True, "exact": False, "suggested": suggested, "duty_rate": duty, "description": desc, "alternatives": alt_codes, "log": log}

    # Step 3: not found
    log = f"Code {code_clean}: NOT FOUND in TARIC database. No alternatives found on prefix '{code_clean[:8]}'."
    print(f"[Validator] {log}")
    return {"found": False, "exact": False, "suggested": "", "duty_rate": "", "description": "", "alternatives": [], "log": log}


def validate(email_body: str, email_subject: str, learned_codes: dict = None) -> dict:
    """
    Main validation function.
    learned_codes: dict {code: {confirmed_code, duty_rate, times_seen, ...}} for cache lookup.
    Returns full result including decision_log for transparency.
    """
    client       = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    decision_log = []

    # ── Step 1: Extract code pairs — regex first, Claude as fallback ───────────
    decision_log.append("STEP 1: Extracting commodity code pairs.")
    combined = (email_subject + " " + email_body).replace("\r", " ")
    code_pairs = []

    # Regex patterns
    for m in re.finditer(r"received[\s:]+([\d]{6,10})[,\s]+suggest\w*[\s:]+([\d]{6,10})", combined, re.IGNORECASE):
        code_pairs.append((m.group(1).strip(), m.group(2).strip()))
    for m in re.finditer(r"[-\u2014]\s*([\d]{6,10})[,\s]+suggest\w*[\s:]+([\d]{6,10})", combined, re.IGNORECASE):
        p = (m.group(1).strip(), m.group(2).strip())
        if p not in code_pairs:
            code_pairs.append(p)
    for m in re.finditer(r"([\d]{6,10})\s*(?:->|\u2192|should be)\s*([\d]{6,10})", combined, re.IGNORECASE):
        p = (m.group(1).strip(), m.group(2).strip())
        if p not in code_pairs:
            code_pairs.append(p)

    # If regex failed — use Claude for extraction only
    if not code_pairs:
        try:
            extract_resp = client.messages.create(
                model=CLAUDE_MODEL, max_tokens=256,
                messages=[{"role": "user", "content": f"""Extract commodity code pairs from this customs email.
Each pair = received code (wrong) → suggested code (proposed as correct).
Return ONLY in this format, one pair per line:
RECEIVED: 1234567890 | SUGGESTED: 9876543210

Examples:
"Received 8413941000, suggesting 8413910090" → RECEIVED: 8413941000 | SUGGESTED: 8413910090
"code 3921906000 should be 3921906090" → RECEIVED: 3921906000 | SUGGESTED: 3921906090

Email subject: {email_subject}
Email body: {email_body[:1500]}

If no codes found: UNKNOWN"""}])
            raw = extract_resp.content[0].text.strip()
            decision_log.append(f"Claude extraction: {raw[:150]}")
            for line in raw.split("\n"):
                if "RECEIVED:" in line.upper() and "SUGGESTED:" in line.upper():
                    try:
                        rec  = re.sub(r"\D", "", line.upper().split("RECEIVED:")[1].split("|")[0]).strip()
                        sugg = re.sub(r"\D", "", line.upper().split("SUGGESTED:")[1]).strip()
                        if rec and sugg:
                            code_pairs.append((rec, sugg))
                    except Exception:
                        pass
        except Exception as e:
            decision_log.append(f"Claude extraction failed: {e}")

    # Last fallback: group all codes as pairs
    if not code_pairs:
        all_found = list(dict.fromkeys(re.findall(r"\b[\d]{8,10}\b", combined)))
        if len(all_found) >= 2:
            for i in range(0, len(all_found) - 1, 2):
                code_pairs.append((all_found[i], all_found[i+1]))
        elif len(all_found) == 1:
            code_pairs = [(all_found[0], all_found[0])]
        else:
            code_pairs = [("UNKNOWN", "UNKNOWN")]

    primary_code = code_pairs[0][0] if code_pairs else "UNKNOWN"
    all_codes    = list({c for pair in code_pairs for c in pair if c != "UNKNOWN"})
    decision_log.append(f"Code pairs extracted: {code_pairs}.")
    print(f"[Validator] Code pairs: {code_pairs}")

    primary_code = code_pairs[0][0] if code_pairs else "UNKNOWN"
    all_codes    = list({c for pair in code_pairs for c in pair if c != "UNKNOWN"})
    decision_log.append(f"Code pairs found: {code_pairs}.")
    print(f"[Validator] Code pairs: {code_pairs}")

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

    # ── Step 4: Descriptions already in results from CSV ────────────────────────
    decision_log.append("STEP 4: Descriptions loaded from CSV in Step 3.")

    # ── Step 5: Build reply programmatically ──────────────────────────────────
    decision_log.append("STEP 5: Building reply from TARIC data only.")
    bullets        = []
    analysis_lines = []
    any_not_found  = False

    for received, result in all_results.items():
        suggested_input = result.get("suggested_input", received)
        if result["exact"]:
            duty = result.get("duty_rate", "")
            desc = result.get("description", "")
            # Suggested = confirmed: toon bevestigd
            status_str = "Confirmed" if suggested_input == received else "Suggested, confirmed"
            bullets.append(
                f"\u2022 {suggested_input}  \u2014  {status_str}"
                + (f"  \u2014  {desc}" if desc else "")
                + (f"  \u2014  Third country tariff: {duty}" if duty else "")
            )
            analysis_lines.append(
                f"Received {received}, suggested {suggested_input}: exact match in TARIC database. Duty: {duty}."
            )
        elif result["found"]:
            best     = result.get("suggested", "")
            duty     = result.get("duty_rate", "")
            desc     = result.get("description", "")
            bullets.append(
                f"\u2022 {best}  \u2014  Suggested, code existed"
                + (f"  \u2014  {desc}" if desc else "")
                + (f"  \u2014  Third country tariff: {duty}" if duty else "")
            )
            analysis_lines.append(
                f"Received {received}, suggested {suggested_input}: not found. Best alternative: {best}"
                + (f" (duty: {duty})" if duty else "") + "."
            )
        else:
            bullets.append(f"\u2022 {suggested_input}  \u2014  Not found in TARIC database.")
            analysis_lines.append(f"Received {received}, suggested {suggested_input}: not found in TARIC database.")
            any_not_found = True

    # Determine resolution type based on actual validation
    all_found_count   = sum(1 for r in all_results.values() if r["found"])
    all_exact_count   = sum(1 for r in all_results.values() if r["exact"])
    any_not_found_res = any(not r["found"] for r in all_results.values())

    if all_exact_count == len(all_results) and all(
        r.get("received","") == r.get("suggested_input","") for r in all_results.values()
    ):
        # All suggested codes confirmed exactly
        code_found      = "true"
        resolution_type = "auto_resolved"
    elif all_found_count == len(all_results):
        # All found but at least one was not exact (received != suggested)
        all_suggested_exact = all(r["exact"] for r in all_results.values())
        code_found      = "true" if all_suggested_exact else "ambiguous"
        resolution_type = "auto_resolved" if all_suggested_exact else "existed"
    elif all_found_count > 0:
        code_found      = "ambiguous"
        resolution_type = "existed"
    else:
        code_found      = "false"
        resolution_type = "not_found"

    follow_up = "\nA DKM specialist will follow up for codes that could not be confirmed." if any_not_found else ""
    analysis  = " ".join(analysis_lines) + f" RESOLUTION_TYPE: {resolution_type}"
    decision_log.append(f"Final resolution: {resolution_type}.")

    # Compact reply using display_pairs
    compact_lines = []
    for received, result in all_results.items():
        suggested_input = result.get("suggested_input", received)
        if result["exact"]:
            duty = result.get("duty_rate","")
            compact_lines.append(
                f"Commodity {received} received  \u2014  {suggested_input} confirmed"
                + (f"  \u2014  Third country tariff: {duty}" if duty else "")
            )
        elif result["found"]:
            best = result.get("suggested","")
            duty = result.get("duty_rate","")
            compact_lines.append(
                f"Commodity {received} received  \u2014  {best} suggested, code existed"
                + (f"  \u2014  Third country tariff: {duty}" if duty else "")
            )
        else:
            compact_lines.append(
                f"Commodity {received} received  \u2014  Not found in TARIC database"
            )

    reply_body = (
        "Dear Team Member,\n\n"
        "I checked your question and below I provide you with my findings.\n\n"
        + "\n".join(compact_lines)
        + (follow_up if any_not_found else "")
        + "\n\n"
        f"AI Analysis: {analysis}\n\n"
        "Kind regards,\nDKM Customs \u2014 Commodity Validation Service"
    )

    # Confirmed code = the validated code
    if csv_result["exact"]:
        confirmed_code = csv_result.get("suggested_input", primary_code)
    elif csv_result["found"]:
        confirmed_code = csv_result.get("suggested", "")
    else:
        confirmed_code = ""

    # Build display pairs: [{received, confirmed, duty, status}]
    display_pairs = []
    for received, result in all_results.items():
        suggested_input = result.get("suggested_input", received)
        if result["exact"]:
            display_pairs.append({
                "received": received,
                "confirmed": suggested_input,
                "duty": result.get("duty_rate",""),
                "status": "confirmed"
            })
        elif result["found"]:
            display_pairs.append({
                "received": received,
                "confirmed": result.get("suggested",""),
                "duty": result.get("duty_rate",""),
                "status": "existed"
            })
        else:
            display_pairs.append({
                "received": received,
                "confirmed": "",
                "duty": "",
                "status": "not_found"
            })

    return {
        "commodity_code":  primary_code,
        "confirmed_code":  confirmed_code,
        "code_found":      code_found,
        "ai_verdict":      analysis,
        "suggested_reply": reply_body,
        "resolution_type": resolution_type,
        "from_cache":      False,
        "decision_log":    " | ".join(decision_log),
        "display_pairs":   json.dumps(display_pairs),
    }
