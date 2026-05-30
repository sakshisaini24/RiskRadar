"""
RiskRadar AI — Pipeline Step 1: Load & Clean
"""

import pandas as pd
import numpy as np
import os
import re

RAW_PATH = "data/raw/RiskRadar_AI_Dataset__2___1_.xlsx"
OUT_STRUCTURED = "data/processed/structured_clean.csv"
OUT_TEXT       = "data/processed/text_clean.csv"
OUT_LABELS     = "data/processed/labels.csv"

# ── 1. LOAD ──────────────────────────────────────────────────────────────────

def load_sheets(path: str) -> dict:
    structured = pd.read_excel(path, sheet_name="Structured Data",   header=1)
    text       = pd.read_excel(path, sheet_name="Unstructured Data", header=1)
    return {"structured": structured, "text": text}

# ── 2. NORMALISE COLUMN NAMES ────────────────────────────────────────────────

def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = []
    for c in df.columns:
        c = str(c).strip()
        c = re.sub(r"[^\w\s]", "", c)
        c = re.sub(r"\s+", "_", c)
        c = c.lower()
        c = re.sub(r"_+", "_", c).strip("_")
        cols.append(c)
    
    # Force absolute uniqueness to prevent DataFrame-instead-of-Series errors
    new_cols = []
    counts = {}
    for col in cols:
        if col in counts:
            counts[col] += 1
            new_cols.append(f"{col}_{counts[col]}")
        else:
            counts[col] = 0
            new_cols.append(col)
    df.columns = new_cols
    return df

# ── 3. CLEAN STRUCTURED DATA ─────────────────────────────────────────────────

# ── 3. CLEAN STRUCTURED DATA ─────────────────────────────────────────────────

RENAME_MAP = {
    "claim_id":            "claim_id",
    "claimant_name":       "claimant_name",
    "age":                 "age",
    "state":               "state",
    "marital_status":      "marital_status",
    "policy_type":         "policy_type",
    "incident_type":       "incident_type",
    "injury_severity":     "injury_severity",
    "incident_date":       "incident_date",
    "filing_date":         "filing_date",
    "days_open":           "days_open",
    "total_claimed_":      "total_claimed",
    "insurer_offer_":      "insurer_offer",
    "approved_amount_":    "approved_amount",
    "settlement_gap_":     "settlement_gap_pct", # Step 2 needs this!
    "deductible_":         "deductible",
    "payment_status":      "payment_status",
    "prior_disputes":      "prior_disputes_raw",
    "legal_rep":           "legal_rep",
    "policy_tenure_yrs":   "policy_tenure_yrs",
    "adjuster_level":      "adjuster_level",
    "followup_contacts":   "followup_contacts",
    "inspections":         "inspections",
    "doc_requests":        "doc_requests",
    "disputed_items":      "disputed_items",
    "state_nv_risk_110":   "state_risk_score",
    "doi_complaint":       "doi_complaint",
    "tplf_suspected":      "tplf_suspected",
    "social_media_threat": "social_media_threat",
    "indep_appraisal":     "indep_appraisal",
    "llm_conflict_score":  "llm_conflict_score",
    "escalation_risk_":    "escalation_risk_pct",
    "target_outcome":      "target_outcome",
}

def clean_structured(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = df.dropna(how="all").reset_index(drop=True)

    # Rename
    col_map = {}
    for col in df.columns:
        for raw_key, clean_name in RENAME_MAP.items():
            if col.startswith(raw_key[:12]):
                col_map[col] = clean_name
                break
    df = df.rename(columns=col_map)

    # Convert dates
    for d_col in ["incident_date", "filing_date"]:
        if d_col in df.columns:
            df[d_col] = pd.to_datetime(df[d_col], errors="coerce")

    # Coerce Numeric
    # Coerce Numeric
    numeric_targets = [
        "age", "days_open", "total_claimed", "insurer_offer", 
        "approved_amount", "settlement_gap_pct", "deductible", 
        "policy_tenure_yrs", "state_risk_score"
    ]
    for col in df.columns:
        if any(target in col for target in numeric_targets):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Target Mapping
    if "target_outcome" in df.columns:
        df["target"] = df["target_outcome"].astype(str).str.lower().str.contains("escalated").astype(int)

    # ── THE FIX: Loop safely using iloc to ensure we handle Series only
    for i in range(len(df.columns)):
        col_name = df.columns[i]
        series = df.iloc[:, i] # This GUARANTEES a Series, even if names were duplicated

        if pd.api.types.is_numeric_dtype(series):
            if series.isnull().any():
                med = series.median()
                df.iloc[:, i] = series.fillna(med if pd.notna(med) else 0)
        else:
            if series.isnull().any():
                mode_res = series.mode()
                fill = mode_res[0] if not mode_res.empty else "Unknown"
                df.iloc[:, i] = series.fillna(fill)
            
    return df

# ── 4. CLEAN TEXT DATA ───────────────────────────────────────────────────────

def clean_text(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = df.dropna(how="all").reset_index(drop=True)
    
    text_rename = {}
    for col in df.columns:
        low = col.lower()
        if "accident" in low or "incident" in low: text_rename[col] = "text_incident"
        elif "adjuster" in low: text_rename[col] = "text_adjuster_notes"
        elif "email" in low: text_rename[col] = "text_email"
        elif "claim" in low: text_rename[col] = "claim_id"

    df = df.rename(columns=text_rename)
    for col in ["text_incident", "text_adjuster_notes", "text_email"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return df

# ── 5. RUN EXPORT ─────────────────────────────────────────────────────────────

def run():
    print("Loading raw data...")
    sheets = load_sheets(RAW_PATH)
    print("Cleaning structured data...")
    structured = clean_structured(sheets["structured"])
    print("Cleaning text data...")
    text = clean_text(sheets["text"])

    os.makedirs("data/processed", exist_ok=True)
    structured.to_csv(OUT_STRUCTURED, index=False)
    text.to_csv(OUT_TEXT, index=False)
    
    if "claim_id" in structured.columns and "target" in structured.columns:
        structured[["claim_id", "target"]].to_csv(OUT_LABELS, index=False)

    print(f"\n{'='*50}\nSuccess! Rows: {len(structured)}\n{'='*50}")
    return structured, text

if __name__ == "__main__":
    run()