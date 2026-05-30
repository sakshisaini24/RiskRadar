"""
Time-to-escalation regressor.

Predicts how long (in days from filing) a claim will take to escalate,
using only the *initial* structured signal — `days_open` is dropped from
features so the model answers the real business question: "for a claim
with THIS profile, when does history say it will escalate?"

Training data: only claims with target_outcome == 'Escalated' from the
frozen train split. We evaluate MAE / R^2 on the escalated claims in the
held-out split.

Artifacts:
  models/time_to_escalation_xgb.json
  models/time_to_escalation_meta.joblib
"""
import os

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

from models.split_utils import load_holdout_ids, load_train_ids

FEATURE_MATRIX = "data/features/feature_matrix.csv"
STRUCTURED_CSV = "data/processed/structured_clean.csv"
MODEL_PATH = "models/time_to_escalation_xgb.json"
META_PATH = "models/time_to_escalation_meta.joblib"

# Features to drop: `days_open` itself (it's the target proxy), plus claim_id/target.
# Keep all other signals — they are things knowable at filing time.
TARGET_COL = "days_open"
DROP_COLS = {"claim_id", "target", "days_open"}


def run():
    print("Loading feature matrix + outcome labels...")
    fm = pd.read_csv(FEATURE_MATRIX)
    fm["claim_id"] = fm["claim_id"].astype(str)
    labels = pd.read_csv(STRUCTURED_CSV)[["claim_id", "target_outcome"]]
    labels["claim_id"] = labels["claim_id"].astype(str)
    df = fm.merge(labels, on="claim_id")  # days_open already in feature_matrix

    # Only escalated claims carry signal for "time-to-escalation"
    df_esc = df[df["target_outcome"] == "Escalated"].copy()
    print(f"Escalated claims available: {len(df_esc)}")

    train_ids = load_train_ids()
    holdout_ids = load_holdout_ids()
    if not train_ids or not holdout_ids:
        raise SystemExit("Missing split. Run models.train_model_a first.")

    tr = df_esc[df_esc["claim_id"].isin(train_ids)]
    te = df_esc[df_esc["claim_id"].isin(holdout_ids)]
    print(f"  train:   {len(tr)}")
    print(f"  holdout: {len(te)}")

    feature_cols = [c for c in df_esc.columns
                    if c not in DROP_COLS and c not in {"target_outcome"}]
    feature_cols = [c for c in feature_cols if df_esc[c].dtype != object]
    feature_cols = [c for c in feature_cols if df_esc[c].nunique() > 1]

    Xtr, ytr = tr[feature_cols].astype(float), tr[TARGET_COL].astype(float)
    Xte, yte = te[feature_cols].astype(float), te[TARGET_COL].astype(float)

    model = xgb.XGBRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        objective="reg:squarederror", random_state=42,
    )
    model.fit(Xtr, ytr)

    pred_te = model.predict(Xte)
    mae = mean_absolute_error(yte, pred_te)
    r2 = r2_score(yte, pred_te) if len(yte) > 1 else float("nan")
    mean_actual = float(yte.mean()) if len(yte) else 0.0

    print("\n=== Holdout evaluation (escalated-only) ===")
    print(f"  MAE:            {mae:.1f} days")
    print(f"  R^2:            {r2:.3f}")
    print(f"  mean actual:    {mean_actual:.1f} days")
    print(f"  naive-baseline MAE (predict mean): "
          f"{abs(yte - ytr.mean()).mean():.1f} days")

    os.makedirs("models", exist_ok=True)
    model.save_model(MODEL_PATH)
    joblib.dump({
        "feature_names": feature_cols,
        "target": TARGET_COL,
        "holdout_mae_days": round(float(mae), 2),
        "holdout_r2": round(float(r2), 4),
        "train_mean_days": float(ytr.mean()),
        "n_train_escalated": int(len(tr)),
        "n_holdout_escalated": int(len(te)),
    }, META_PATH)
    print(f"\nSaved to {MODEL_PATH}")


if __name__ == "__main__":
    run()
