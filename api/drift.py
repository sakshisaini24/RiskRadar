"""
Population Stability Index (PSI) drift monitor.

Compares the feature distributions the model was TRAINED on against the
distribution in the HOLDOUT set. In production this would compare
training vs. the last 30 days of live traffic — same math, different
reference window.

PSI interpretation (industry standard):
    < 0.10   stable
    0.10–0.25 moderate drift — retrain candidate
    > 0.25   significant drift — retrain required
"""
from typing import Dict, List

import numpy as np
import pandas as pd

from models.split_utils import load_holdout_ids, load_train_ids

FEATURE_MATRIX = "data/features/feature_matrix.csv"

# Features we actually care about monitoring. Skip claim_id/target and the
# zero-variance ones.
MONITOR_FEATURES = [
    "days_to_file", "offer_to_claim_ratio", "log_claim_amount",
    "settlement_gap_pct", "policy_tenure_yrs", "followup_contacts",
    "doc_requests", "disputed_items", "inspections",
    "has_legal_rep", "high_state_risk", "is_junior_adjuster",
]


def _psi(reference: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
    """Compute PSI between two 1-D arrays using quantile bins from `reference`."""
    ref = reference[~np.isnan(reference)]
    cur = current[~np.isnan(current)]
    if len(ref) == 0 or len(cur) == 0:
        return 0.0
    # Quantile edges from reference. Duplicates dropped so discrete features work.
    edges = np.quantile(ref, np.linspace(0, 1, n_bins + 1))
    edges = np.unique(edges)
    if len(edges) < 3:
        return 0.0
    edges[0] = -np.inf
    edges[-1] = np.inf

    ref_hist, _ = np.histogram(ref, bins=edges)
    cur_hist, _ = np.histogram(cur, bins=edges)

    ref_pct = ref_hist / max(ref_hist.sum(), 1)
    cur_pct = cur_hist / max(cur_hist.sum(), 1)

    # Laplace smoothing so log(0) can't happen
    eps = 1e-4
    ref_pct = np.clip(ref_pct, eps, None)
    cur_pct = np.clip(cur_pct, eps, None)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return round(max(psi, 0.0), 4)


def _severity(psi: float) -> str:
    if psi < 0.10:
        return "stable"
    if psi < 0.25:
        return "moderate"
    return "significant"


def compute() -> Dict:
    try:
        fm = pd.read_csv(FEATURE_MATRIX)
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}
    fm["claim_id"] = fm["claim_id"].astype(str).str.strip()
    train_ids = load_train_ids()
    holdout_ids = load_holdout_ids()
    if not train_ids or not holdout_ids:
        return {"status": "no_split"}

    train_df = fm[fm["claim_id"].isin(train_ids)]
    holdout_df = fm[fm["claim_id"].isin(holdout_ids)]

    rows: List[Dict] = []
    for feat in MONITOR_FEATURES:
        if feat not in fm.columns:
            continue
        ref = train_df[feat].to_numpy(dtype=float, copy=False)
        cur = holdout_df[feat].to_numpy(dtype=float, copy=False)
        psi = _psi(ref, cur)
        rows.append({
            "feature": feat,
            "psi": psi,
            "severity": _severity(psi),
            "train_mean": round(float(np.nanmean(ref)), 4) if len(ref) else None,
            "current_mean": round(float(np.nanmean(cur)), 4) if len(cur) else None,
            "mean_delta_pct": round(
                (float(np.nanmean(cur)) - float(np.nanmean(ref)))
                / max(abs(float(np.nanmean(ref))), 1e-6) * 100, 2
            ) if len(ref) and len(cur) else None,
        })

    rows.sort(key=lambda r: r["psi"], reverse=True)
    status = "stable"
    if any(r["severity"] == "significant" for r in rows):
        status = "drift_detected"
    elif any(r["severity"] == "moderate" for r in rows):
        status = "watch"

    return {
        "status": status,
        "n_reference": int(len(train_df)),
        "n_current": int(len(holdout_df)),
        "reference_window": "training set",
        "current_window": "held-out set (proxy for last 30 days in production)",
        "features": rows,
        "notes": (
            "PSI < 0.10 stable · 0.10–0.25 moderate · > 0.25 significant. "
            "In production the 'current' window would be rolling live traffic."
        ),
    }
