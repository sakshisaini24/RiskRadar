"""
Fit an isotonic calibration on the ensemble's holdout predictions.

Why isotonic: the raw ensemble outputs a weighted average of two XGBoost
models. XGBoost probabilities are notoriously miscalibrated (S-shaped
reliability curves). Isotonic regression learns a monotonic mapping from
raw score -> true frequency of escalation, so when we say "risk = 72%"
the real-world frequency actually matches.

Output: models/calibrator.joblib — a fitted sklearn IsotonicRegression.
"""
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from models.ensemble import RiskRadarEnsemble
from models.split_utils import load_holdout_ids, HOLDOUT_PATH

CALIBRATOR_PATH = "models/calibrator.joblib"
STRUCTURED_CSV = "data/processed/structured_clean.csv"


def _load_holdout_labels():
    holdout_df = pd.read_csv(HOLDOUT_PATH)
    holdout_df["claim_id"] = holdout_df["claim_id"].astype(str).str.strip()
    return holdout_df


def run():
    holdout = _load_holdout_labels()
    if holdout.empty:
        raise SystemExit("Holdout file missing. Run models.train_model_a first.")

    print(f"Fitting isotonic calibrator on {len(holdout)} holdout claims...")
    engine = RiskRadarEnsemble()

    raw_probs, labels = [], []
    for _, row in holdout.iterrows():
        cid = row["claim_id"]
        result = engine.get_risk_score(cid)
        if not result:
            continue
        raw_probs.append(result["risk_score_pct"] / 100.0)
        labels.append(int(row["target"]))

    raw_probs = np.array(raw_probs)
    labels = np.array(labels)

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw_probs, labels)

    # Spot-check a few reference points
    for p in [0.1, 0.3, 0.5, 0.7, 0.9]:
        print(f"  raw {p:.2f}  ->  calibrated {float(iso.predict([p])[0]):.3f}")

    os.makedirs(os.path.dirname(CALIBRATOR_PATH), exist_ok=True)
    joblib.dump(
        {
            "model": iso,
            "n_calibration": len(labels),
            "holdout_positive_rate": float(labels.mean()),
        },
        CALIBRATOR_PATH,
    )
    print(f"\nSaved calibrator to {CALIBRATOR_PATH}")


if __name__ == "__main__":
    run()
