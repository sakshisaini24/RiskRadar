"""
End-to-end evaluation report for RiskRadar.

Two scenarios are evaluated side-by-side so judges can see realistic
performance, not just the near-perfect numbers the synthetic dataset
allows:

  - "full"        : all features, including engineered NLP scores
                    (nlp_risk_score, trigger_score, email_trigger_score, etc.)
                    These features are derived from a trigger-phrase lexicon
                    applied to the same text the label was generated from,
                    so they correlate >0.9 with target on this dataset.

  - "adversarial" : same pipeline WITHOUT those lexicon-derived features.
                    The model must learn escalation risk from raw TF-IDF +
                    base structured features only. This is the realistic
                    lower-bound on how the system would generalise to new
                    data where the trigger lexicon may not be baked in.

Artifacts written to  data/features/eval/:
    eval_report.json           aggregate metrics for both scenarios
    calibration_curve.png      reliability diagram
    pr_curve.png               precision/recall tradeoff
    lift_chart.png             model lift vs. random baseline
    confusion_matrices.png     CM at 3 thresholds (0.35, 0.50, 0.65)
"""
import json
import os

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import calibration_curve
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)

from models.split_utils import HOLDOUT_PATH, TRAIN_PATH

OUT_DIR = "data/features/eval"
FEATURE_MATRIX = "data/features/feature_matrix.csv"
TEXT_CSV = "data/processed/text_clean.csv"
STRUCTURED_CSV = "data/processed/structured_clean.csv"

# Features that are computed FROM the same text that produced the label.
# On this synthetic dataset they correlate >0.86 with target. We drop them
# in the "adversarial" scenario to show realistic performance.
LEXICON_LEAKAGE_FEATURES = [
    "nlp_risk_score",
    "trigger_score",
    "email_trigger_score",
    "trigger_count",
    "llm_conflict_score",
    "combined_sentiment",
    "adjuster_negative_tone",
]


def _load_split():
    train_df = pd.read_csv(TRAIN_PATH)
    test_df = pd.read_csv(HOLDOUT_PATH)
    train_df["claim_id"] = train_df["claim_id"].astype(str)
    test_df["claim_id"] = test_df["claim_id"].astype(str)
    return train_df, test_df


def _train_structured_xgb(X_train, y_train):
    pos_weight = (len(y_train) - sum(y_train)) / max(sum(y_train), 1)
    m = xgb.XGBClassifier(
        objective="binary:logistic", eval_metric="logloss",
        scale_pos_weight=pos_weight,
        max_depth=4, learning_rate=0.05, n_estimators=150, random_state=42,
    )
    m.fit(X_train, y_train)
    return m


def _train_text_xgb(texts_train, y_train):
    vec = TfidfVectorizer(stop_words="english", max_features=1000, ngram_range=(1, 2))
    X_train = vec.fit_transform(texts_train)
    pos_weight = (len(y_train) - sum(y_train)) / max(sum(y_train), 1)
    m = xgb.XGBClassifier(
        objective="binary:logistic", eval_metric="logloss",
        scale_pos_weight=pos_weight,
        max_depth=4, learning_rate=0.05, n_estimators=150, random_state=42,
    )
    m.fit(X_train, y_train)
    return m, vec


def _scenario_scores(scenario_name, drop_features, include_text=True,
                     mask_trigger_words=False):
    """Train both models on TRAIN split with optional feature drop, predict on HOLDOUT."""
    train_ids_df, test_ids_df = _load_split()

    # Structured side
    fm = pd.read_csv(FEATURE_MATRIX)
    fm["claim_id"] = fm["claim_id"].astype(str)
    feature_cols = [c for c in fm.columns if c not in ("claim_id", "target")]
    feature_cols = [c for c in feature_cols if c not in drop_features]
    # Remove zero-variance columns
    feature_cols = [c for c in feature_cols if fm[c].nunique() > 1]

    train_mask = fm["claim_id"].isin(set(train_ids_df["claim_id"]))
    test_mask = fm["claim_id"].isin(set(test_ids_df["claim_id"]))
    Xa_train = fm.loc[train_mask, feature_cols]
    Xa_test = fm.loc[test_mask, feature_cols]
    ya_train = fm.loc[train_mask, "target"]
    ya_test = fm.loc[test_mask, "target"]
    model_a = _train_structured_xgb(Xa_train, ya_train)
    probs_a = model_a.predict_proba(Xa_test)[:, 1]

    order_a = fm.loc[test_mask, "claim_id"].tolist()
    y_test = ya_test.values

    if not include_text:
        # Structured-only: no Model B, no ensemble
        return {
            "name": scenario_name,
            "y_test": y_test,
            "raw_probs": probs_a,
            "calibrated_probs": _fit_isotonic(probs_a, y_test),
            "n_features": len(feature_cols),
            "text_used": False,
        }

    # Text side
    td = pd.read_csv(TEXT_CSV)
    td["claim_id"] = td["claim_id"].astype(str)
    labels_df = pd.read_csv(STRUCTURED_CSV)[["claim_id", "target"]]
    labels_df["claim_id"] = labels_df["claim_id"].astype(str)
    td = td.merge(labels_df, on="claim_id")
    text_cols = [c for c in td.columns if any(k in c.lower() for k in
                 ["desc", "note", "transcript", "email", "text"])]
    td["combined_text"] = td[text_cols].fillna("").astype(str).agg(" ".join, axis=1)

    if mask_trigger_words:
        # Replace the exact lexicon that generated the label with a token
        # so TF-IDF cannot trivially look up "attorney" or "lawsuit"
        from pipeline.step_03_nlp_features import TRIGGER_PHRASES
        masked_terms = sorted(TRIGGER_PHRASES.keys(), key=len, reverse=True)
        import re as _re
        pattern = _re.compile("|".join(_re.escape(t) for t in masked_terms),
                              flags=_re.IGNORECASE)
        td["combined_text"] = td["combined_text"].str.replace(pattern, "__MASKED__",
                                                               regex=True)

    tr = td[td["claim_id"].isin(set(train_ids_df["claim_id"]))]
    te = td[td["claim_id"].isin(set(test_ids_df["claim_id"]))]
    model_b, vec = _train_text_xgb(tr["combined_text"], tr["target"])
    probs_b = model_b.predict_proba(vec.transform(te["combined_text"]))[:, 1]

    # Ensemble 40/60 to match production
    order_b = te["claim_id"].tolist()
    pb_by_id = dict(zip(order_b, probs_b))
    probs_b_aligned = np.array([pb_by_id.get(cid, 0.5) for cid in order_a])
    ensemble_probs = probs_a * 0.4 + probs_b_aligned * 0.6

    print(f"[{scenario_name}] features used: {len(feature_cols)}, "
          f"raw AUC={roc_auc_score(y_test, ensemble_probs):.3f}")

    return {
        "name": scenario_name,
        "y_test": y_test,
        "raw_probs": ensemble_probs,
        "calibrated_probs": _fit_isotonic(ensemble_probs, y_test),
        "n_features": len(feature_cols),
        "text_used": True,
    }


def _fit_isotonic(probs, y):
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)
    iso.fit(probs, y)
    return iso.predict(probs)


def _metrics_at(y_true, probs, threshold):
    pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    return {
        "threshold": threshold,
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _plot_calibration(scenarios, path):
    plt.figure(figsize=(7, 6))
    plt.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")
    for s in scenarios:
        frac_pos, mean_pred = calibration_curve(
            s["y_test"], s["calibrated_probs"], n_bins=10, strategy="quantile"
        )
        plt.plot(mean_pred, frac_pos, marker="o", label=f"{s['name']} (n={len(s['y_test'])})")
    plt.xlabel("Predicted probability")
    plt.ylabel("Observed escalation rate")
    plt.title("Calibration curve (reliability diagram) — holdout")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _plot_pr(scenarios, path):
    plt.figure(figsize=(7, 6))
    for s in scenarios:
        prec, rec, _ = precision_recall_curve(s["y_test"], s["calibrated_probs"])
        ap = average_precision_score(s["y_test"], s["calibrated_probs"])
        plt.plot(rec, prec, label=f"{s['name']} — AP={ap:.3f}")
    baseline = scenarios[0]["y_test"].mean()
    plt.axhline(baseline, ls="--", color="gray", alpha=0.5,
                label=f"Random baseline = {baseline:.2f}")
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title("Precision–Recall curve — holdout")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _plot_lift(scenarios, path):
    plt.figure(figsize=(7, 6))
    for s in scenarios:
        order = np.argsort(-s["calibrated_probs"])
        y_sorted = s["y_test"][order]
        cum_positives = np.cumsum(y_sorted)
        total_positives = cum_positives[-1] if cum_positives[-1] > 0 else 1
        deciles = np.linspace(0, 1, len(y_sorted))
        plt.plot(deciles, cum_positives / total_positives, label=s["name"])
    plt.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Random")
    plt.xlabel("Fraction of claims reviewed (highest risk first)")
    plt.ylabel("Fraction of escalations caught")
    plt.title("Cumulative gains / lift — holdout")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _plot_confusion_matrices(scenarios, path):
    thresholds = [0.35, 0.50, 0.65]
    fig, axes = plt.subplots(len(scenarios), len(thresholds),
                             figsize=(4 * len(thresholds), 3.5 * len(scenarios)))
    if len(scenarios) == 1:
        axes = np.array([axes])
    for i, s in enumerate(scenarios):
        for j, t in enumerate(thresholds):
            m = _metrics_at(s["y_test"], s["calibrated_probs"], t)
            cm = np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]])
            ax = axes[i, j]
            ax.imshow(cm, cmap="Blues")
            for (r, c), val in np.ndenumerate(cm):
                ax.text(c, r, str(val), ha="center", va="center",
                        color="white" if val > cm.max() / 2 else "black", fontsize=14)
            ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
            ax.set_xticklabels(["Resolved", "Escalated"])
            ax.set_yticklabels(["Resolved", "Escalated"])
            ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
            ax.set_title(f"{s['name']} — t={t}\n"
                         f"recall={m['recall']:.2f} precision={m['precision']:.2f}")
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def run():
    os.makedirs(OUT_DIR, exist_ok=True)

    scenarios = [
        _scenario_scores("full", drop_features=[]),
        _scenario_scores("adversarial_text",
                         drop_features=LEXICON_LEAKAGE_FEATURES,
                         include_text=True,
                         mask_trigger_words=True),
        _scenario_scores("structured_only",
                         drop_features=LEXICON_LEAKAGE_FEATURES,
                         include_text=False),
    ]

    # Generate plots
    _plot_calibration(scenarios, os.path.join(OUT_DIR, "calibration_curve.png"))
    _plot_pr(scenarios, os.path.join(OUT_DIR, "pr_curve.png"))
    _plot_lift(scenarios, os.path.join(OUT_DIR, "lift_chart.png"))
    _plot_confusion_matrices(scenarios, os.path.join(OUT_DIR, "confusion_matrices.png"))

    # Build aggregate JSON report
    report = {"scenarios": {}}
    for s in scenarios:
        y_true = s["y_test"]
        probs = s["calibrated_probs"]
        report["scenarios"][s["name"]] = {
            "n_features_used": s["n_features"],
            "roc_auc": round(roc_auc_score(y_true, probs), 4),
            "average_precision": round(average_precision_score(y_true, probs), 4),
            "positive_rate": round(float(y_true.mean()), 4),
            "threshold_sweep": [
                _metrics_at(y_true, probs, t) for t in [0.35, 0.50, 0.65]
            ],
        }
    report["dropped_in_adversarial"] = LEXICON_LEAKAGE_FEATURES
    report["split"] = {
        "train": len(pd.read_csv(TRAIN_PATH)),
        "holdout": len(pd.read_csv(HOLDOUT_PATH)),
    }

    with open(os.path.join(OUT_DIR, "eval_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("\n=== Evaluation Report ===")
    print(json.dumps(report, indent=2))
    print(f"\nArtifacts written to {OUT_DIR}/")


if __name__ == "__main__":
    run()
