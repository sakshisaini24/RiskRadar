"""Held-out validation metrics for the calibrated escalation risk model.

IMPORTANT: evaluation runs ONLY on the frozen holdout claim_ids saved at
training time (data/features/holdout_claim_ids.csv). This guarantees the
numbers the dashboard shows are true out-of-sample, not leakage from training.
"""
import pandas as pd
from api.risk_calibrator import calibrate_risk
from api.trigger_phrases import detect_triggers
from models.split_utils import load_holdout_ids

METRICS_CACHE = {
    "status": "not_computed",
    "split": "holdout",
    "total_evaluated": 0,
    "threshold": 50.0,
    "confusion_matrix": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
    "precision": 0.0,
    "recall": 0.0,
    "f1": 0.0,
    "accuracy": 0.0,
    "baseline_random_recall": 0.5,
    "notes": "",
}

# Raw (y_true, proba) pairs from the most recent compute_metrics run. The API
# exposes these so the UI can recompute the confusion matrix live as the
# adjuster drags a threshold slider.
HOLDOUT_SCORES: dict = {"y_true": [], "y_pred_proba": [], "claim_ids": []}


def _find_outcome_column(df):
    for c in ["outcome", "TARGET: Outcome", "target_outcome", "target"]:
        if c in df.columns:
            return c
    return None


def compute_metrics(ensemble, structured_df, threshold=50.0, max_claims=None,
                    unstructured_df=None, genai_df=None):
    """Run calibrated ensemble on every claim, compare to ground truth."""
    if structured_df.empty:
        METRICS_CACHE["status"] = "no_data"
        METRICS_CACHE["notes"] = "Structured dataset is empty."
        return METRICS_CACHE

    outcome_col = _find_outcome_column(structured_df)
    if outcome_col is None:
        METRICS_CACHE["status"] = "no_ground_truth"
        return METRICS_CACHE

    holdout_ids = load_holdout_ids()
    if not holdout_ids:
        METRICS_CACHE["status"] = "no_holdout"
        METRICS_CACHE["notes"] = (
            "No holdout split found. Re-run training (python -m models.train_model_a) "
            "so data/features/holdout_claim_ids.csv is created."
        )
        return METRICS_CACHE

    claim_ids = [cid for cid in structured_df["claim_id"].astype(str).tolist()
                 if cid in holdout_ids]
    if max_claims:
        claim_ids = claim_ids[:max_claims]

    y_true, y_pred_proba, scored_ids = [], [], []
    skipped = 0

    has_unstructured = unstructured_df is not None and not unstructured_df.empty

    for cid in claim_ids:
        try:
            raw = ensemble.get_risk_score(cid)
            if not raw:
                skipped += 1
                continue

            # Get unstructured for this claim
            email_text, adjuster_text, triggers = "", "", None
            if has_unstructured:
                u_match = unstructured_df[unstructured_df["Claim ID"] == cid]
                if not u_match.empty:
                    row = u_match.iloc[0]
                    email_text = str(row.get("Email Transcript — Claimant (Unstructured)", "") or "")
                    adjuster_text = str(row.get("Adjuster Field Notes (Unstructured)", "") or "")
                    triggers = detect_triggers(cid, email_text, adjuster_text, genai_df=genai_df)

            calibrated = calibrate_risk(raw, triggers, email_text, adjuster_text)
            outcome = structured_df.loc[structured_df["claim_id"] == cid, outcome_col].iloc[0]
            y_true.append(1 if str(outcome).strip().lower() == "escalated" else 0)
            y_pred_proba.append(float(calibrated.get("risk_score_pct", 0)))
            scored_ids.append(cid)
        except Exception as e:
            skipped += 1
            print(f"[metrics] Skipping {cid}: {e}")

    if not y_true:
        METRICS_CACHE["status"] = "no_predictions"
        return METRICS_CACHE

    tp = fp = tn = fn = 0
    for t, p in zip(y_true, y_pred_proba):
        pred = 1 if p >= threshold else 0
        if pred == 1 and t == 1: tp += 1
        elif pred == 1 and t == 0: fp += 1
        elif pred == 0 and t == 0: tn += 1
        else: fn += 1

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / total if total else 0.0
    positive_rate = (tp + fn) / total if total else 0.0

    METRICS_CACHE.update({
        "status": "ok",
        "split": "holdout",
        "total_evaluated": total,
        "skipped": skipped,
        "threshold": threshold,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "baseline_random_recall": round(positive_rate, 4),
        "notes": f"Held-out evaluation: {total} claims (never seen in training) at threshold {threshold}%.",
    })
    HOLDOUT_SCORES["y_true"] = y_true
    HOLDOUT_SCORES["y_pred_proba"] = y_pred_proba
    HOLDOUT_SCORES["claim_ids"] = scored_ids

    print(f"[metrics] Holdout: recall={recall:.3f}, precision={precision:.3f}, f1={f1:.3f}, n={total}")
    return METRICS_CACHE


def get_metrics():
    return METRICS_CACHE


def get_holdout_scores():
    """Return raw (claim_id, y_true, calibrated_prob) triples for UI sliders."""
    return {
        "n": len(HOLDOUT_SCORES["y_true"]),
        "claim_ids": HOLDOUT_SCORES["claim_ids"],
        "y_true": HOLDOUT_SCORES["y_true"],
        "y_pred_proba": HOLDOUT_SCORES["y_pred_proba"],
    }