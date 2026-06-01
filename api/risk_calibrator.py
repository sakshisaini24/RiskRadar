"""
Hybrid risk calibrator. Wraps the raw ensemble with:
1. Learned isotonic calibration (fit on held-out data). Falls back to
   temperature scaling if the fitted calibrator isn't available yet.
2. Unstructured signal blending using trigger phrase severity.
3. Cooperative language detection to dampen scores when warranted.
"""
import math
import os
import re
import joblib

# Tunable parameters
TEMPERATURE = 1.6            # fallback only — used if calibrator.joblib missing
STRUCTURED_WEIGHT = 0.70
UNSTRUCTURED_WEIGHT = 0.30

CALIBRATOR_PATH = "models/calibrator.joblib"
_CALIBRATOR = None
_CALIBRATOR_META = {}


def _load_calibrator():
    global _CALIBRATOR, _CALIBRATOR_META
    if _CALIBRATOR is not None or not os.path.exists(CALIBRATOR_PATH):
        return
    try:
        bundle = joblib.load(CALIBRATOR_PATH)
        _CALIBRATOR = bundle["model"]
        _CALIBRATOR_META = {k: v for k, v in bundle.items() if k != "model"}
        print(f"[risk_calibrator] Loaded isotonic calibrator "
              f"(n={_CALIBRATOR_META.get('n_calibration')})")
    except Exception as e:
        print(f"[risk_calibrator] Failed to load calibrator: {e}")


_load_calibrator()

# Trigger phrase severity → score impact (out of 100)
SEVERITY_IMPACT = {
    "critical": 25,
    "high": 16,
    "medium": 8,
    "low": 3,
}

COOPERATIVE_PHRASES = [
    "thank you", "thanks", "appreciate", "patient", "understand",
    "no rush", "no urgency", "happy to", "willing to", "cooperative",
    "look forward", "in good hands", "good communication",
    "no concerns", "received and reviewed", "moves forward on schedule",
    "checking in", "just confirming", "all good", "smooth",
]

ADDITIONAL_HOSTILE = [
    "unacceptable", "frustrated", "frustrating", "disappointed",
    "ridiculous", "demand", "insist", "refuse", "outraged",
    "fed up", "supervisor", "complaint", "escalate this",
    "wasting my time", "incompetent", "negligent",
]


def _temperature_scale(p_raw_pct, temperature=TEMPERATURE):
    """Fallback calibration: pull extreme probabilities toward 50%."""
    p = max(0.001, min(0.999, p_raw_pct / 100.0))
    logit = math.log(p / (1 - p))
    scaled = logit / temperature
    return round(1 / (1 + math.exp(-scaled)) * 100, 2)


def _isotonic_scale(p_raw_pct):
    """Learned calibration via IsotonicRegression fit on the holdout."""
    if _CALIBRATOR is None:
        return _temperature_scale(p_raw_pct)
    p = max(0.0, min(1.0, p_raw_pct / 100.0))
    calibrated = float(_CALIBRATOR.predict([p])[0])
    return round(calibrated * 100, 2)


def calibration_method():
    """Returns which calibration method is active — used by /metrics."""
    return "isotonic" if _CALIBRATOR is not None else "temperature_scaling"


def _unstructured_score(trigger_analysis, email_text, adjuster_text, raw_pct):
    """
    Compute 0-100 score from unstructured signals.
    Baseline anchored to the raw ML score (so we don't artificially lift quiet claims).
    """
    combined_text = f"{email_text or ''} {adjuster_text or ''}".lower()

    has_triggers = bool(trigger_analysis and trigger_analysis.get("phrases"))
    cooperative_hits = sum(1 for p in COOPERATIVE_PHRASES if p in combined_text)
    hostile_hits = sum(1 for p in ADDITIONAL_HOSTILE if p in combined_text)

    # Anchor baseline to the ML model's hint (avoids manufacturing risk where none exists)
    if raw_pct < 5:
        baseline = 5.0
    elif raw_pct < 15:
        baseline = 12.0
    elif raw_pct > 90:
        baseline = 70.0
    else:
        baseline = 35.0

    score = baseline

    # Apply trigger impact (severity-weighted)
    if has_triggers:
        for phrase in trigger_analysis["phrases"]:
            severity = phrase.get("severity", "medium")
            score += SEVERITY_IMPACT.get(severity, 5)

    # Hostile language adds; cooperative language subtracts
    score += hostile_hits * 5
    score -= cooperative_hits * 4

    # If absolutely no risk signals AND multiple cooperative cues, push score very low
    if not has_triggers and hostile_hits == 0 and cooperative_hits >= 2:
        score = min(score, 8.0)

    # If many hostile signals, ensure floor of MEDIUM
    if hostile_hits >= 3 or (has_triggers and len(trigger_analysis["phrases"]) >= 4):
        score = max(score, 55.0)

    return max(2.0, min(98.0, score))


def calibrate_risk(raw_results, trigger_analysis=None, email_text="", adjuster_text=""):
    """Returns calibrated risk results combining structured + unstructured signal."""
    if not raw_results:
        return None

    raw_pct = float(raw_results.get("risk_score_pct", 0))

    structured_calibrated = _isotonic_scale(raw_pct)
    unstructured_pct = _unstructured_score(trigger_analysis, email_text, adjuster_text, raw_pct)

    # Avoid double-counting: when ML already scores very high, cap text-layer lift
    if structured_calibrated >= 85:
        unstructured_pct = min(unstructured_pct, structured_calibrated + 12)

    final_pct = (
        structured_calibrated * STRUCTURED_WEIGHT
        + unstructured_pct * UNSTRUCTURED_WEIGHT
    )
    # Compress top bucket so high-risk claims spread across ~88–97 instead of all 99%
    if final_pct > 90:
        final_pct = 90 + (final_pct - 90) * 0.55
    final_pct = round(max(1.0, min(97.0, final_pct)), 2)

    is_high_risk = final_pct >= 60.0  # match frontend's 60% red threshold

    return {
        **raw_results,
        "risk_score_pct": final_pct,
        "is_high_risk": is_high_risk,
        "calibration": {
            "raw_ml_score": round(raw_pct, 2),
            "structured_calibrated": structured_calibrated,
            "unstructured_score": round(unstructured_pct, 2),
            "method": calibration_method(),
            "weights": {
                "structured": STRUCTURED_WEIGHT,
                "unstructured": UNSTRUCTURED_WEIGHT,
            },
            "final": final_pct,
        },
    }