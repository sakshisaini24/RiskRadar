"""
RiskRadar AI — Pipeline Step 3: NLP Feature Extraction
Processes the three free-text fields to extract:
  - Sentiment score per field
  - Trigger phrase detection (legal threats, hostility signals)
  - Combined text risk score
Output: nlp_features.csv
"""

import pandas as pd
import numpy as np
import re
import os

IN_PATH  = "data/processed/text_clean.csv"
OUT_PATH = "data/features/nlp_features.csv"


# ── TRIGGER PHRASE DICTIONARIES ───────────────────────────────────────────────
# Grouped by risk level (weight 3 = highest risk signal)

TRIGGER_PHRASES = {
    # Legal escalation signals — weight 3
    "attorney":              3,
    "lawyer":                3,
    "litigation":            3,
    "file a lawsuit":        3,
    "going to court":        3,
    "legal action":          3,
    "sue":                   3,
    "my attorney":           3,
    "doi complaint":         3,
    "ombudsman":             3,
    "consumer forum":        3,
    "ncdrc":                 3,
    "insurance tribunal":    3,
    # Hostility / frustration signals — weight 2
    "unacceptable":          2,
    "disgusted":             2,
    "outrageous":            2,
    "threatening":           2,
    "demand":                2,
    "bad faith":             2,
    "fraud":                 2,
    "cheated":               2,
    "scam":                  2,
    "report you":            2,
    "social media":          2,
    "news":                  2,
    "expose":                2,
    "escalate":              2,
    "not satisfied":         2,
    "will not accept":       2,
    # Delay / dispute signals — weight 1
    "why is it taking":      1,
    "still waiting":         1,
    "no response":           1,
    "follow up":             1,
    "ignored":               1,
    "delayed":               1,
    "unreasonable":          1,
    "dispute":               1,
    "disagree":              1,
    "independent appraisal": 1,
    "second opinion":        1,
}

# Positive / cooperative signals reduce risk score
COOPERATIVE_PHRASES = [
    "thank you", "thanks", "appreciate", "cooperative",
    "happy with", "satisfied", "good communication",
    "in good hands", "moving forward", "all good",
    "no issues", "ready to proceed",
]


# ── SIMPLE LEXICON-BASED SENTIMENT ───────────────────────────────────────────
# (No external model needed — fast and explainable)

POSITIVE_WORDS = set([
    "good", "great", "excellent", "happy", "satisfied", "pleased",
    "thank", "appreciate", "helpful", "smooth", "quick", "easy",
    "resolved", "clear", "cooperative", "wonderful", "perfect",
])

NEGATIVE_WORDS = set([
    "bad", "terrible", "awful", "angry", "frustrated", "upset",
    "disappointed", "unacceptable", "outrageous", "disgusted",
    "delay", "slow", "unfair", "wrong", "denied", "rejected",
    "demand", "sue", "threat", "fraud", "cheat", "scam", "lie",
])

def lexicon_sentiment(text: str) -> float:
    """
    Returns a sentiment score from -1.0 (very negative) to +1.0 (very positive).
    Uses simple word counting — no external model required.
    """
    if not text or text.strip() == "":
        return 0.0
    words = re.findall(r"\b\w+\b", text.lower())
    if not words:
        return 0.0
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


# ── TRIGGER PHRASE DETECTION ──────────────────────────────────────────────────

def detect_triggers(text: str) -> dict:
    """
    Scans text for trigger phrases. Returns:
      - trigger_score: weighted sum of all matches
      - trigger_count: number of distinct phrases found
      - triggers_found: list of matched phrases (for UI display)
    """
    if not text:
        return {"trigger_score": 0, "trigger_count": 0, "triggers_found": []}

    text_lower = text.lower()
    found = []
    score = 0

    for phrase, weight in TRIGGER_PHRASES.items():
        if phrase in text_lower:
            found.append(phrase)
            score += weight

    # Subtract cooperative signals
    for phrase in COOPERATIVE_PHRASES:
        if phrase in text_lower:
            score = max(0, score - 1)

    return {
        "trigger_score": score,
        "trigger_count": len(found),
        "triggers_found": "; ".join(found) if found else "",
    }


# ── PROCESS ALL THREE TEXT FIELDS ────────────────────────────────────────────

def extract_nlp_features(df: pd.DataFrame) -> pd.DataFrame:
    results = []

    for _, row in df.iterrows():
        incident_text = str(row.get("text_incident", ""))
        adjuster_text = str(row.get("text_adjuster_notes", ""))
        email_text    = str(row.get("text_email", ""))

        # Sentiment per field
        sentiment_incident = lexicon_sentiment(incident_text)
        sentiment_adjuster = lexicon_sentiment(adjuster_text)
        sentiment_email    = lexicon_sentiment(email_text)

        # Weighted average: email carries most weight (most adversarial signal)
        combined_sentiment = round(
            0.25 * sentiment_incident +
            0.30 * sentiment_adjuster +
            0.45 * sentiment_email,
            4
        )

        # Trigger detection — run on concatenated text for full picture
        all_text = f"{incident_text} {adjuster_text} {email_text}"
        triggers = detect_triggers(all_text)

        # Email-specific triggers (most predictive for escalation)
        email_triggers = detect_triggers(email_text)

        # Adjuster tone signal (negative adjuster notes = adversarial case)
        adjuster_negative = 1 if sentiment_adjuster < -0.1 else 0

        # Combined NLP risk score (0–100)
        # Formula: normalised trigger score + sentiment penalty
        nlp_risk_raw = (
            triggers["trigger_score"] * 4 +          # triggers are strong signals
            email_triggers["trigger_score"] * 6 +     # email triggers especially strong
            (1 - combined_sentiment) * 10 +            # negative sentiment adds risk
            adjuster_negative * 10                     # hostile adjuster notes
        )
        nlp_risk_score = min(100, round(nlp_risk_raw, 1))

        results.append({
            "claim_id":               row.get("claim_id", ""),
            "sentiment_incident":     sentiment_incident,
            "sentiment_adjuster":     sentiment_adjuster,
            "sentiment_email":        sentiment_email,
            "combined_sentiment":     combined_sentiment,
            "trigger_score":          triggers["trigger_score"],
            "trigger_count":          triggers["trigger_count"],
            "triggers_found":         triggers["triggers_found"],
            "email_trigger_score":    email_triggers["trigger_score"],
            "adjuster_negative_tone": adjuster_negative,
            "nlp_risk_score":         nlp_risk_score,
        })

    return pd.DataFrame(results)


def run():
    print("Loading clean text data...")
    df = pd.read_csv(IN_PATH)

    print(f"Extracting NLP features from {len(df)} claims...")
    nlp_df = extract_nlp_features(df)

    os.makedirs("data/features", exist_ok=True)
    nlp_df.to_csv(OUT_PATH, index=False)

    print(f"\n{'='*50}")
    print(f"NLP features: {nlp_df.shape[0]} rows × {nlp_df.shape[1]} cols")
    print(f"\nTrigger phrase stats:")
    print(f"  Claims with any trigger: {(nlp_df['trigger_count'] > 0).sum()}")
    print(f"  Avg trigger score:       {nlp_df['trigger_score'].mean():.2f}")
    print(f"  Avg combined sentiment:  {nlp_df['combined_sentiment'].mean():.3f}")
    print(f"  Avg NLP risk score:      {nlp_df['nlp_risk_score'].mean():.1f}")
    print(f"\nTop 5 highest NLP risk claims:")
    top5 = nlp_df.nlargest(5, "nlp_risk_score")[["claim_id", "nlp_risk_score", "triggers_found"]]
    print(top5.to_string(index=False))
    print(f"\nSaved: {OUT_PATH}")
    print("="*50)

    return nlp_df


if __name__ == "__main__":
    run()