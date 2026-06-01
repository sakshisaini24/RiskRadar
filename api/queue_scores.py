"""
Fast batch scoring for the triage queue.

Scores all dataset claims in a few vectorized passes instead of
550 sequential get_risk_score() calls.
"""
from typing import Any, Dict, Optional

import pandas as pd

from api.risk_calibrator import calibrate_risk
from api.trigger_phrases import detect_triggers


def _combine_text(row: pd.Series, text_cols: list) -> str:
    parts = []
    for col in text_cols:
        v = row.get(col)
        if pd.notna(v) and str(v).strip():
            parts.append(str(v).strip())
    return " ".join(parts)


def build_queue_score_cache(
    ensemble,
    genai_df: Optional[pd.DataFrame] = None,
    unstructured_by_id: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Batch-score every claim in feature_matrix. Returns claim_id -> score dict.
    Full calibrate_risk + triggers per claim (cheap); ML inference is batched.
    """
    fm = ensemble.feature_matrix.copy()
    fm["claim_id"] = fm["claim_id"].astype(str).str.strip()
    names = ensemble.meta_a["feature_names"]
    threshold = float(ensemble.meta_a.get("optimal_threshold", 0.5))

    X_a = fm[names].astype(float)
    prob_a = ensemble.model_a.predict_proba(X_a)[:, 1]

    td = ensemble.text_data.copy()
    td["claim_id"] = td["claim_id"].astype(str).str.strip()
    text_cols = [c for c in ensemble.text_cols if c in td.columns]
    merged = fm[["claim_id"]].merge(td, on="claim_id", how="left")
    combined_texts = merged.apply(lambda r: _combine_text(r, text_cols), axis=1)
    X_b = ensemble.vectorizer_b.transform(combined_texts.tolist())
    prob_b = ensemble.model_b.predict_proba(X_b)[:, 1]

    final_prob = (prob_a * 0.4) + (prob_b * 0.6)
    unstructured_by_id = unstructured_by_id or {}

    cache: Dict[str, Dict[str, Any]] = {}
    for i, cid in enumerate(fm["claim_id"]):
        raw_pct = float(round(final_prob[i] * 100, 2))
        raw_results = {
            "claim_id": cid,
            "risk_score_pct": raw_pct,
            "is_high_risk": bool(final_prob[i] >= threshold),
            "model_a_contribution": float(round(prob_a[i] * 100, 1)),
            "model_b_contribution": float(round(prob_b[i] * 100, 1)),
            "top_warning_signs": [],
            "scoring_mode": "queue_batch",
        }

        u = unstructured_by_id.get(cid, {})
        email_text = u.get("email_text", "")
        adjuster_text = u.get("adjuster_text", "")
        triggers = detect_triggers(cid, email_text, adjuster_text, genai_df=genai_df)
        calibrated = calibrate_risk(raw_results, triggers, email_text, adjuster_text)
        if not calibrated:
            cache[cid] = {
                "risk_score_pct": raw_pct,
                "is_high_risk": raw_pct >= 60.0,
            }
            continue
        cache[cid] = {
            "risk_score_pct": float(calibrated["risk_score_pct"]),
            "is_high_risk": bool(calibrated["is_high_risk"]),
        }

    return cache
