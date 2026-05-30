"""
Time-to-escalation inference wrapper.

Given a claim_id, returns:
  predicted_escalation_day : expected days_open at which escalation occurs,
                              based on claims with similar profile
  days_remaining           : predicted_escalation_day - current days_open
  mae_days                 : the model's holdout MAE (for UI uncertainty text)

If the fitted artifacts are missing, returns None so callers can skip
this panel gracefully.
"""
import os
from typing import Optional

import joblib
import pandas as pd
import xgboost as xgb

FEATURE_MATRIX = "data/features/feature_matrix.csv"
STRUCTURED_CSV = "data/processed/structured_clean.csv"
MODEL_PATH = "models/time_to_escalation_xgb.json"
META_PATH = "models/time_to_escalation_meta.joblib"

_MODEL: Optional[xgb.XGBRegressor] = None
_META: dict = {}
_FEATURE_MATRIX: Optional[pd.DataFrame] = None
_STRUCTURED: Optional[pd.DataFrame] = None


def _load():
    global _MODEL, _META, _FEATURE_MATRIX, _STRUCTURED
    if _MODEL is not None:
        return
    if not (os.path.exists(MODEL_PATH) and os.path.exists(META_PATH)):
        print("[time_to_escalation] Model not trained yet — skipping.")
        return
    try:
        m = xgb.XGBRegressor()
        m.load_model(MODEL_PATH)
        _MODEL = m
        _META = joblib.load(META_PATH)
        fm = pd.read_csv(FEATURE_MATRIX)
        fm["claim_id"] = fm["claim_id"].astype(str).str.strip()
        _FEATURE_MATRIX = fm
        sd = pd.read_csv(STRUCTURED_CSV)[["claim_id", "days_open"]]
        sd["claim_id"] = sd["claim_id"].astype(str).str.strip()
        _STRUCTURED = sd
        print(f"[time_to_escalation] Loaded (holdout MAE={_META.get('holdout_mae_days')} days)")
    except Exception as e:
        print(f"[time_to_escalation] Failed to load: {e}")


_load()


def predict_timeline(claim_id: str) -> Optional[dict]:
    """Return time-to-escalation forecast for a claim, or None if unavailable."""
    if _MODEL is None or _FEATURE_MATRIX is None:
        return None
    cid = str(claim_id).strip()
    row = _FEATURE_MATRIX[_FEATURE_MATRIX["claim_id"] == cid]
    if row.empty:
        return None

    features = _META["feature_names"]
    # Subset to the trained feature list; fill any missing as 0
    X = row.reindex(columns=features, fill_value=0).astype(float)
    try:
        predicted_day = float(_MODEL.predict(X)[0])
    except Exception as e:
        print(f"[time_to_escalation] Predict failed for {cid}: {e}")
        return None

    predicted_day = max(1.0, predicted_day)

    # Current days_open (if known) — derive days_remaining
    cur = None
    if _STRUCTURED is not None:
        match = _STRUCTURED[_STRUCTURED["claim_id"] == cid]
        if not match.empty:
            cur = float(match.iloc[0]["days_open"])

    days_remaining = (predicted_day - cur) if cur is not None else None
    if days_remaining is not None:
        days_remaining = round(days_remaining, 1)

    mae = _META.get("holdout_mae_days", 0)

    # Build a human-readable label used by the UI
    if days_remaining is None:
        label = f"Similar profiles historically escalate around day {predicted_day:.0f}"
    elif days_remaining <= 0:
        label = f"Escalation risk window reached (historical median day {predicted_day:.0f}; claim is {cur:.0f} days old)"
    elif days_remaining < 14:
        label = f"Escalation likely within ~{int(round(days_remaining))} days (±{mae:.0f})"
    else:
        label = f"Expected escalation window: ~{int(round(days_remaining))} days (±{mae:.0f})"

    return {
        "predicted_escalation_day": round(predicted_day, 1),
        "current_days_open": cur,
        "days_remaining": days_remaining,
        "mae_days": mae,
        "holdout_r2": _META.get("holdout_r2"),
        "label": label,
        "n_training_claims": _META.get("n_train_escalated"),
    }


def model_stats() -> dict:
    return {
        "available": _MODEL is not None,
        "mae_days": _META.get("holdout_mae_days"),
        "holdout_r2": _META.get("holdout_r2"),
        "n_training_claims": _META.get("n_train_escalated"),
        "n_holdout": _META.get("n_holdout_escalated"),
    }
