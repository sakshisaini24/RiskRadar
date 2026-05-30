"""Compares Groq and Gemini outputs to detect agreement/disagreement as a signal."""


def _extract_risk_signal(text):
    """Detect HIGH / MEDIUM / LOW / UNAVAILABLE from model text."""
    if not text:
        return "UNAVAILABLE"

    lower = text.lower()

    # Detect API errors first
    error_signals = ["error:", "404", "is not found", "is not supported",
                     "api key", "rate limit", "quota exceeded"]
    if any(sig in lower for sig in error_signals):
        return "UNAVAILABLE"

    # Suspiciously short = no real analysis
    if len(text.strip()) < 50:
        return "UNAVAILABLE"

    high_markers = [
        "high risk", "high-risk", "severe", "critical", "urgent", "imminent",
        "likely to escalate", "significant risk", "substantial risk", "red flag",
        "aggressive", "litigation", "attorney involvement", "bad faith",
        "hostile", "threatening", "demand letter",
    ]
    low_markers = [
        "low risk", "low-risk", "minimal risk", "unlikely to escalate",
        "standard processing", "routine", "cooperative", "no significant",
        "no red flag", "straightforward", "amicable", "satisfied",
    ]
    medium_markers = [
        "moderate", "medium", "some concern", "monitor", "watch closely",
    ]

    high_hits = sum(1 for m in high_markers if m in lower)
    low_hits = sum(1 for m in low_markers if m in lower)
    medium_hits = sum(1 for m in medium_markers if m in lower)

    # Strong majority required for HIGH/LOW to avoid noise
    if high_hits >= 2 and high_hits > low_hits + medium_hits:
        return "HIGH"
    if low_hits >= 2 and low_hits > high_hits + medium_hits:
        return "LOW"
    if medium_hits >= 1 and medium_hits >= high_hits and medium_hits >= low_hits:
        return "MEDIUM"
    if high_hits > low_hits:
        return "HIGH"
    if low_hits > high_hits:
        return "LOW"
    return "MEDIUM"


def analyze_consensus(groq_text, gemini_text, ml_risk_pct):
    """Returns structured consensus analysis with smart handling of unavailable models."""
    groq_signal = _extract_risk_signal(groq_text)
    gemini_signal = _extract_risk_signal(gemini_text)

    # ML signal from calibrated score
    if ml_risk_pct >= 70:
        ml_signal = "HIGH"
    elif ml_risk_pct >= 40:
        ml_signal = "MEDIUM"
    else:
        ml_signal = "LOW"

    # Filter out unavailable models for agreement analysis
    available_signals = []
    if groq_signal != "UNAVAILABLE":
        available_signals.append(("Groq", groq_signal))
    if gemini_signal != "UNAVAILABLE":
        available_signals.append(("Gemini", gemini_signal))

    # Special case: nothing available — fall back to ML alone
    if not available_signals:
        return {
            "status": "ml_only",
            "agreement": False,
            "message": (
                f"AI strategist models are unavailable for this claim. "
                f"Recommendation based solely on ML model: {ml_signal} risk."
            ),
            "signals": {
                "groq": groq_signal,
                "gemini": gemini_signal,
                "ml_model": ml_signal,
            },
        }

    # Only one model available
    if len(available_signals) == 1:
        name, sig = available_signals[0]
        agree_with_ml = sig == ml_signal
        unavailable_name = "Gemini" if name == "Groq" else "Groq"
        return {
            "status": "single_model" if agree_with_ml else "single_model_disagree",
            "agreement": agree_with_ml,
            "message": (
                f"{name} agrees with ML model ({ml_signal}). "
                f"{unavailable_name} unavailable."
                if agree_with_ml else
                f"{name} ({sig}) disagrees with ML ({ml_signal}). "
                f"{unavailable_name} unavailable. Consider human review."
            ),
            "signals": {
                "groq": groq_signal,
                "gemini": gemini_signal,
                "ml_model": ml_signal,
            },
        }

    # Both models available — original consensus logic
    sig_set = set(s for _, s in available_signals)
    if len(sig_set) == 1 and list(sig_set)[0] == ml_signal:
        status = "strong_agreement"
        agreement = True
        message = f"All systems agree: {ml_signal} risk. High confidence in this assessment."
    elif len(sig_set) == 1:
        status = "model_consensus"
        agreement = True
        sig = list(sig_set)[0]
        message = f"Both LLMs agree on {sig} risk; ML model says {ml_signal}. Worth reviewing calibration."
    else:
        status = "disagreement"
        agreement = False
        message = (
            f"Models disagree (Groq: {groq_signal}, Gemini: {gemini_signal}). "
            f"This claim sits in an ambiguous zone — recommend senior adjuster review."
        )

    return {
        "status": status,
        "agreement": agreement,
        "message": message,
        "signals": {
            "groq": groq_signal,
            "gemini": gemini_signal,
            "ml_model": ml_signal,
        },
    }