"""Trigger phrase detection for claimant communications."""
import re
import pandas as pd

# Curated red-flag phrases, grouped by severity for UI coloring
TRIGGER_LEXICON = {
    "critical": [
        "bad faith", "nuclear verdict", "civil remedy notice", "demand letter",
        "third-party funder", "third party funder", "class action", "punitive damages",
        "department of insurance", "doi complaint", "file a complaint",
        "my attorney will be in touch", "formal demand",
    ],
    "high": [
        "attorney", "lawyer", "legal counsel", "legal action", "litigation",
        "lawsuit", "sue", "court", "unfair settlement practices", "statutory damages",
        "civil suit", "state statute", "regulatory",
    ],
    "medium": [
        "unacceptable", "insulting", "outrageous", "furious", "outraged",
        "refuse to accept", "refuse to pay", "dragging", "stalling",
        "bad faith denial", "discrimination", "deceptive", "misrepresentation",
    ],
    "low": [
        "dissatisfied", "frustrated", "still waiting", "disappointed",
        "concerned", "escalate", "manager", "supervisor",
    ],
}

SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _load_precomputed_phrases(genai_df, claim_id):
    """Try to load pre-computed phrases from the GenAI layer dataframe."""
    if genai_df is None or genai_df.empty:
        return []
    match = genai_df[genai_df["Claim ID"] == claim_id]
    if match.empty:
        return []
    raw = match.iloc[0].get("Detected Trigger Phrases / Entities (LLM)")
    if pd.isna(raw) or not raw:
        return []
    text = str(raw).strip()
    if text.lower() in {"none detected", "none", "nan"}:
        return []
    # Split on semicolons (primary) or commas (fallback)
    parts = re.split(r"[;,]", text)
    return [p.strip() for p in parts if p.strip()]


def _classify_severity(phrase):
    p = phrase.lower()
    for sev, words in TRIGGER_LEXICON.items():
        for w in words:
            if w in p or p in w:
                return sev
    return "medium"  # default if pre-computed phrase didn't match lexicon


def _find_matches_in_text(phrases, text):
    """Find character offsets of each phrase in the text. Case-insensitive."""
    matches = []
    if not text:
        return matches
    lower = text.lower()
    for phrase in phrases:
        pat = re.escape(phrase.lower())
        for m in re.finditer(pat, lower):
            matches.append({
                "phrase": text[m.start():m.end()],
                "start": m.start(),
                "end": m.end(),
                "severity": _classify_severity(phrase),
            })
    # Sort by position, dedupe overlapping
    matches.sort(key=lambda x: (x["start"], -x["end"]))
    deduped = []
    last_end = -1
    for m in matches:
        if m["start"] >= last_end:
            deduped.append(m)
            last_end = m["end"]
    return deduped


def _dynamic_phrase_list():
    """Flatten the lexicon into a single list for fallback detection."""
    out = []
    for sev, words in TRIGGER_LEXICON.items():
        out.extend(words)
    return out


def detect_triggers(claim_id, email_text, adjuster_text, genai_df=None):
    """
    Returns {
      'phrases': ['attorney', 'bad faith', ...],   # deduplicated list of phrase strings
      'email_matches': [{phrase, start, end, severity}, ...],
      'adjuster_matches': [...],
      'source': 'precomputed' | 'dynamic' | 'hybrid',
      'risk_weight': int,  # aggregate severity score
    }
    """
    precomputed = _load_precomputed_phrases(genai_df, claim_id)
    source = "precomputed" if precomputed else "dynamic"

    phrase_pool = list(precomputed)
    if not phrase_pool:
        phrase_pool = _dynamic_phrase_list()
    else:
        # Hybrid: add dynamic phrases too, just in case the precomputed list missed some
        phrase_pool = list(set(phrase_pool + _dynamic_phrase_list()))
        source = "hybrid"

    email_matches = _find_matches_in_text(phrase_pool, email_text or "")
    adjuster_matches = _find_matches_in_text(phrase_pool, adjuster_text or "")

    seen = set()
    unique_phrases = []
    risk_weight = 0
    for m in email_matches + adjuster_matches:
        key = m["phrase"].lower()
        if key not in seen:
            seen.add(key)
            unique_phrases.append({"phrase": m["phrase"], "severity": m["severity"]})
            risk_weight += SEVERITY_WEIGHT.get(m["severity"], 1)

    return {
        "phrases": unique_phrases,
        "email_matches": email_matches,
        "adjuster_matches": adjuster_matches,
        "source": source,
        "risk_weight": risk_weight,
    }