"""
RiskRadar AI — Pipeline Step 4: Merge & Export Final Feature Matrix
Joins structured features + NLP features on claim_id.
Output: features/feature_matrix.csv  — this is what the ML models train on.
"""

import pandas as pd
import numpy as np
import os

IN_STRUCTURED = "data/features/structured_features.csv"
IN_NLP        = "data/features/nlp_features.csv"
OUT_PATH      = "data/features/feature_matrix.csv"
OUT_REPORT    = "data/features/feature_report.txt"


def run():
    print("Loading structured features...")
    struct_df = pd.read_csv(IN_STRUCTURED)

    print("Loading NLP features...")
    nlp_df = pd.read_csv(IN_NLP)

    # Drop non-feature columns from NLP before merge (keep only numeric signals)
    nlp_keep = [
        "claim_id",
        "combined_sentiment",
        "trigger_score",
        "trigger_count",
        "email_trigger_score",
        "adjuster_negative_tone",
        "nlp_risk_score",
    ]
    nlp_df = nlp_df[[c for c in nlp_keep if c in nlp_df.columns]]

    print("Merging on claim_id...")
    df = struct_df.merge(nlp_df, on="claim_id", how="left")

    # Fill any NLP nulls (claims that had no text) with 0
    nlp_numeric_cols = [c for c in nlp_keep if c != "claim_id"]
    for col in nlp_numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    # Final combined risk score (ensemble preview — averaged structured + NLP)
    if "escalation_risk_pct" in struct_df.columns:
        # Use the pre-computed score as a baseline alongside our features
        pass

    os.makedirs("data/features", exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    # ── FEATURE REPORT ────────────────────────────────────────────────────────
    feature_cols = [c for c in df.columns if c not in ["claim_id", "target", "target_outcome"]]
    target = df["target"] if "target" in df.columns else None

    report_lines = [
        "RiskRadar AI — Feature Matrix Report",
        "=" * 50,
        f"Total claims:     {len(df)}",
        f"Total features:   {len(feature_cols)}",
        "",
    ]

    if target is not None:
        escalated = int(target.sum())
        resolved  = int((target == 0).sum())
        report_lines += [
            "Target distribution:",
            f"  Resolved (0):   {resolved}  ({resolved/len(df)*100:.1f}%)",
            f"  Escalated (1):  {escalated}  ({escalated/len(df)*100:.1f}%)",
            "",
        ]

    report_lines.append("All features in matrix:")
    for col in feature_cols:
        dtype = str(df[col].dtype)
        nulls = int(df[col].isna().sum())
        if target is not None and df[col].dtype in [np.float64, np.int64, float, int]:
            corr = round(abs(df[col].corr(target)), 3)
            report_lines.append(f"  {col:<40} dtype={dtype:<8} nulls={nulls}  |target corr|={corr}")
        else:
            report_lines.append(f"  {col:<40} dtype={dtype:<8} nulls={nulls}")

    report_lines += [
        "",
        "Top 15 features by correlation with target:",
    ]
    if target is not None:
        num_cols = df[feature_cols].select_dtypes(include=[np.number]).columns
        corrs = df[num_cols].corrwith(target).abs().sort_values(ascending=False)
        for feat, val in corrs.head(15).items():
            report_lines.append(f"  {feat:<40} {val:.4f}")

    report_text = "\n".join(report_lines)
    print("\n" + report_text)

    with open(OUT_REPORT, "w") as f:
        f.write(report_text)

    print(f"\nSaved: {OUT_PATH}")
    print(f"Saved: {OUT_REPORT}")

    return df


if __name__ == "__main__":
    run()