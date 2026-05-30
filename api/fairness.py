"""
Fairness audit: recall + precision stratified by protected-ish attributes.

Insurance regulators (NAIC, IRDAI, state DOIs) require evidence that a
risk-scoring model doesn't systematically under-detect escalations for
particular demographics. This module slices the holdout predictions by
state, age bucket, and policy type, computing per-group metrics plus
the disparity vs. the overall recall at the current threshold.
"""
from typing import Dict, List, Optional

import pandas as pd

from api.metrics import HOLDOUT_SCORES

STRUCTURED_CSV = "data/processed/structured_clean.csv"


def _age_bucket(age):
    try:
        a = float(age)
    except Exception:
        return "Unknown"
    if a < 30:
        return "< 30"
    if a < 45:
        return "30–44"
    if a < 60:
        return "45–59"
    return "60+"


def _build_frame(threshold: float) -> Optional[pd.DataFrame]:
    if not HOLDOUT_SCORES["claim_ids"]:
        return None
    df = pd.DataFrame({
        "claim_id": HOLDOUT_SCORES["claim_ids"],
        "y_true": HOLDOUT_SCORES["y_true"],
        "y_pred_proba": HOLDOUT_SCORES["y_pred_proba"],
    })
    df["claim_id"] = df["claim_id"].astype(str).str.strip()
    try:
        struct = pd.read_csv(STRUCTURED_CSV)
        struct["claim_id"] = struct["claim_id"].astype(str).str.strip()
        cols = ["claim_id", "state", "age", "policy_type", "incident_type"]
        cols = [c for c in cols if c in struct.columns]
        df = df.merge(struct[cols], on="claim_id", how="left")
    except Exception:
        return None
    df["y_pred"] = (df["y_pred_proba"] >= threshold).astype(int)
    df["age_bucket"] = df["age"].apply(_age_bucket)
    return df


def _group_metrics(sub: pd.DataFrame) -> Dict:
    tp = int(((sub["y_pred"] == 1) & (sub["y_true"] == 1)).sum())
    fp = int(((sub["y_pred"] == 1) & (sub["y_true"] == 0)).sum())
    tn = int(((sub["y_pred"] == 0) & (sub["y_true"] == 0)).sum())
    fn = int(((sub["y_pred"] == 0) & (sub["y_true"] == 1)).sum())
    pos = tp + fn
    neg = tn + fp
    return {
        "n": int(len(sub)),
        "escalations": pos,
        "recall": round(tp / pos, 4) if pos else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "fpr": round(fp / neg, 4) if neg else None,
        "base_rate": round(pos / len(sub), 4) if len(sub) else None,
    }


def compute(threshold: float = 50.0, min_group_n: int = 5) -> Dict:
    df = _build_frame(threshold)
    if df is None:
        return {"status": "unavailable",
                "note": "Holdout scores not computed yet — start the API and hit /metrics."}

    overall = _group_metrics(df)
    slices: Dict[str, List[Dict]] = {}

    for attr, key in [("state", "state"), ("age_bucket", "age_bucket"),
                      ("policy_type", "policy_type")]:
        if attr not in df.columns:
            continue
        rows = []
        for group_val, sub in df.groupby(attr):
            m = _group_metrics(sub)
            if m["n"] < min_group_n or m["recall"] is None:
                continue
            disparity = round(m["recall"] - (overall["recall"] or 0), 4)
            rows.append({
                "group": str(group_val),
                **m,
                "recall_disparity_vs_overall": disparity,
            })
        rows.sort(key=lambda r: r["recall"] or 0)
        slices[key] = rows

    # Flag the worst recall gap across all slices
    worst = None
    for k, rows in slices.items():
        for r in rows:
            if r["recall"] is None:
                continue
            gap = (overall["recall"] or 0) - r["recall"]
            if worst is None or gap > worst["gap"]:
                worst = {
                    "attribute": k,
                    "group": r["group"],
                    "gap": round(float(gap), 4),
                    "group_recall": r["recall"],
                    "overall_recall": overall["recall"],
                    "n": r["n"],
                }

    return {
        "status": "ok",
        "threshold": threshold,
        "min_group_n": min_group_n,
        "overall": overall,
        "slices": slices,
        "worst_recall_gap": worst,
        "notes": (
            "Recall disparity is (group_recall - overall_recall). Negative values "
            "mean the model under-detects escalations for that group."
        ),
    }
