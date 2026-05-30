"""
RiskRadar AI — Pipeline Step 2: Structured Feature Engineering
Reads the clean structured CSV and engineers 12 new predictive features,
then encodes categoricals. Output: structured_features.csv
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
import os

IN_PATH  = "data/processed/structured_clean.csv"
OUT_PATH = "data/features/structured_features.csv"


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["incident_date", "filing_date"])
    return df


# ── ENGINEERED FEATURES ───────────────────────────────────────────────────────

def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:

    # 1. Days between incident and filing
    if "incident_date" in df.columns and "filing_date" in df.columns:
        df["days_to_file"] = (df["filing_date"] - df["incident_date"]).dt.days
        df["days_to_file"] = df["days_to_file"].clip(lower=0)
        med = df["days_to_file"].median()
        df["days_to_file"] = df["days_to_file"].fillna(med if pd.notna(med) else 0)
    else:
        df["days_to_file"] = 0

    # 2. Offer-to-claim ratio
    if "total_claimed" in df.columns and "insurer_offer" in df.columns:
        df["offer_to_claim_ratio"] = np.where(
            df["total_claimed"] > 0,
            df["insurer_offer"] / df["total_claimed"],
            0
        )
        df["offer_to_claim_ratio"] = df["offer_to_claim_ratio"].clip(0, 1)
    else:
        df["offer_to_claim_ratio"] = 0

    # 3. Settlement gap flag (Must match Step 1 name)
    if "settlement_gap_pct" in df.columns:
        df["large_settlement_gap"] = (df["settlement_gap_pct"] > 40).astype(int)
    else:
        df["large_settlement_gap"] = 0

    # 4. Dispute density score
    df["dispute_density"] = (
        df["followup_contacts"].fillna(0) if "followup_contacts" in df.columns else 0 +
        df["doc_requests"].fillna(0) if "doc_requests" in df.columns else 0 +
        df["disputed_items"].fillna(0) if "disputed_items" in df.columns else 0 +
        (df["inspections"].fillna(0) * 2 if "inspections" in df.columns else 0)
    )

    # 5. Legal pressure index
    df["legal_pressure_index"] = (
        (df["doi_complaint"].fillna(0) * 3 if "doi_complaint" in df.columns else 0) +
        (df["tplf_suspected"].fillna(0) * 3 if "tplf_suspected" in df.columns else 0) +
        (df["social_media_threat"].fillna(0) * 2 if "social_media_threat" in df.columns else 0) +
        (df["indep_appraisal"].fillna(0) * 1 if "indep_appraisal" in df.columns else 0)
    )

    # 6. Has legal representation
    if "legal_rep" in df.columns:
        attorney_keywords = ["attorney", "lawyer", "litigation", "legal", "counsel", "adjuster"]
        df["has_legal_rep"] = df["legal_rep"].astype(str).str.lower().apply(
            lambda x: 1 if any(kw in x for kw in attorney_keywords) else 0
        )
    else:
        df["has_legal_rep"] = 0

    # 7. Is junior adjuster
    if "adjuster_level" in df.columns:
        df["is_junior_adjuster"] = (
            df["adjuster_level"].astype(str).str.lower().str.contains("junior", na=False)
        ).astype(int)
    else:
        df["is_junior_adjuster"] = 0

    # 8. High state risk (FIXED: Using Series comparison)
    if "state_risk_score" in df.columns:
        df["high_state_risk"] = (df["state_risk_score"].fillna(0) >= 7).astype(int)
    else:
        df["high_state_risk"] = 0

    # 9. Claim age category
    days_open_ser = df["days_open"] if "days_open" in df.columns else pd.Series([0] * len(df))
    df["claim_age_bucket"] = pd.cut(
        days_open_ser.fillna(0),
        bins=[-1, 30, 90, 180, 365, 99999],
        labels=[0, 1, 2, 3, 4]
    ).astype(float).fillna(0)

    # 10. Prior disputes × legal rep
    prior = df["prior_disputes"] if "prior_disputes" in df.columns else 0
    df["prior_disputes_x_legal"] = prior * df["has_legal_rep"]

    # 11. Claim amount tier
    claimed = df["total_claimed"] if "total_claimed" in df.columns else 0
    df["log_claim_amount"] = np.log1p(claimed.fillna(0))

    # 12. Short policy tenure (FIXED: Using Series comparison)
    if "policy_tenure_yrs" in df.columns:
        df["short_tenure"] = (df["policy_tenure_yrs"].fillna(10) < 2).astype(int)
    else:
        df["short_tenure"] = 0

    return df


# ── ENCODE CATEGORICALS ───────────────────────────────────────────────────────

CATEGORICAL_COLS = [
    "policy_type", "incident_type", "injury_severity",
    "adjuster_level", "payment_status", "marital_status", "state",
]

def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    encoders = {}
    for col in CATEGORICAL_COLS:
        if col in df.columns:
            le = LabelEncoder()
            df[f"{col}_enc"] = le.fit_transform(df[col].astype(str))
            encoders[col] = dict(zip(le.classes_, le.transform(le.classes_)))
    return df, encoders


# ── SELECT FINAL FEATURE COLUMNS ─────────────────────────────────────────────

FEATURE_COLS = [
    "days_to_file", "offer_to_claim_ratio", "large_settlement_gap",
    "dispute_density", "legal_pressure_index", "has_legal_rep",
    "is_junior_adjuster", "high_state_risk", "claim_age_bucket",
    "prior_disputes_x_legal", "log_claim_amount", "short_tenure",
    "days_open", "settlement_gap_pct", "prior_disputes",
    "policy_tenure_yrs", "state_risk_score", "llm_conflict_score",
    "followup_contacts", "doc_requests", "disputed_items", "inspections",
    "policy_type_enc", "incident_type_enc", "injury_severity_enc",
    "adjuster_level_enc", "payment_status_enc",
]


def run():
    print("Loading clean structured data...")
    df = load(IN_PATH)

    print("Engineering features...")
    df = add_engineered_features(df)

    print("Encoding categoricals...")
    df, encoders = encode_categoricals(df)

    # Keep ID + target + features
    keep_cols = ["claim_id", "target"] + [c for c in FEATURE_COLS if c in df.columns]
    features_df = df[keep_cols].copy()

    os.makedirs("data/features", exist_ok=True)
    features_df.to_csv(OUT_PATH, index=False)

    print(f"\n{'='*50}")
    print(f"Feature matrix: {features_df.shape[0]} rows × {features_df.shape[1]} cols")
    
    if "target" in features_df.columns:
        print(f"\nTop feature correlations with target:")
        num_features = features_df.select_dtypes(include=[np.number]).drop(columns=["target"], errors="ignore")
        corr = num_features.corrwith(features_df["target"]).abs().sort_values(ascending=False)
        for feat, val in corr.head(10).items():
            print(f"  {feat:<35} {val:.3f}")
            
    print(f"\nSaved: {OUT_PATH}")
    print("="*50)

    return features_df


if __name__ == "__main__":
    run()