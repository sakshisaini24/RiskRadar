"""Curated US insurance precedents for demos when CourtListener API is unavailable."""
from typing import Any, Dict, List, Optional


def _cases_for_query(incident_type: str, matched_query: str) -> List[Dict[str, Any]]:
    incident = (incident_type or "").lower()
    query = (matched_query or "").lower()
    theft = any(k in incident + query for k in ("theft", "stolen", "vehicle"))
    bad_faith = any(
        k in query for k in ("attorney", "litigation", "bad faith", "legal", "supervisor")
    )

    if theft:
        theme = "theft"
    elif bad_faith:
        theme = "bad_faith"
    else:
        theme = "general"

    by_theme = {
        "theft": _THEFT_CASES,
        "bad_faith": _BAD_FAITH_CASES,
        "general": _GENERAL_CASES,
    }
    return [dict(c) for c in by_theme.get(theme, _GENERAL_CASES)]


def demo_us_precedents(
    incident_type: str,
    trigger_phrases: Optional[list] = None,
    top_warnings: Optional[list] = None,
) -> tuple[List[Dict[str, Any]], str, str]:
    """Returns (cases, status, matched_query) for live demos without CourtListener."""
    parts = [incident_type or "insurance claim"]
    if trigger_phrases:
        for p in trigger_phrases[:2]:
            phrase = p.get("phrase", "") if isinstance(p, dict) else str(p)
            if phrase:
                parts.append(phrase)
    if top_warnings:
        parts.extend(str(w) for w in top_warnings[:2] if w)
    matched_query = " ".join(parts).strip()
    if "insurance" not in matched_query.lower():
        matched_query = f"insurance {matched_query}"
    if len(matched_query) > 120:
        matched_query = matched_query[:120]

    cases = _cases_for_query(incident_type, matched_query)
    for c in cases:
        c["relevance_note"] = (
            f"Demo library — retrieved for '{matched_query}' "
            f"(CourtListener fallback for finals)."
        )
        c["match_query"] = matched_query
    return cases, "demo_fallback", matched_query


_GENERAL_CASES = [
    {
        "docid": "demo-us-egan",
        "title": "Egan v. Mutual of Omaha Insurance Co.",
        "headline": "Insurer must conduct a thorough, fair investigation before denying a claim.",
        "snippet": (
            "The California Supreme Court held that when an insurer denies coverage it must "
            "base the decision on a reasonable investigation of all available evidence, not "
            "selective review favoring denial."
        ),
        "court": "Supreme Court of California",
        "date_filed": "1980-02-19",
        "jurisdiction": "US",
        "url": "https://www.courtlistener.com/opinion/117051/egan-v-mutual-of-omaha-insurance-co/",
        "spotlight_brief": (
            "Egan v. Mutual of Omaha Insurance Co. (Cal. 1980) establishes that an insurer "
            "must investigate a claim thoroughly and fairly before denying coverage. The court "
            "rejected a shallow review that ignored evidence supporting the insured. For open "
            "high-risk files, adjusters should document investigation steps before any denial "
            "or low settlement position."
        ),
        "spotlight_relevance": (
            "This opinion applies when escalation risk is driven by disputed investigation "
            "quality and delayed insurer response. It supports immediate senior review and "
            "a documented coverage position before the claimant retains counsel."
        ),
    },
    {
        "docid": "demo-us-crisci",
        "title": "Crisci v. Security Insurance Co. of New Haven",
        "headline": "Insurer bad faith includes failure to settle within policy limits when exposure is clear.",
        "snippet": (
            "The court held the insurer acted in bad faith by failing to accept a reasonable "
            "settlement within policy limits when the probability of an excess verdict was substantial."
        ),
        "court": "Court of Appeal of California",
        "date_filed": "1966-08-30",
        "jurisdiction": "US",
        "url": "https://www.courtlistener.com/opinion/2254376/crisci-v-security-insurance-co-of-new-haven/",
        "spotlight_brief": (
            "Crisci v. Security Insurance Co. addresses insurer settlement strategy when "
            "liability exposure exceeds policy limits. The insurer must give the insured's "
            "interests equal consideration with its own. High settlement-gap claims with "
            "litigation threats require early settlement authority review."
        ),
        "spotlight_relevance": (
            "Relevant where the claimant alleges an unacceptable offer and threatens litigation. "
            "Supports escalating settlement authority before demand-letter deadlines expire."
        ),
    },
    {
        "docid": "demo-us-gruenberg",
        "title": "Gruenberg v. Aetna Insurance Co.",
        "headline": "Improper claim handling and denial without reasonable basis can support bad-faith liability.",
        "snippet": (
            "The court found bad faith where the insurer's handling of the claim showed "
            "an intent to avoid payment rather than a good-faith coverage determination."
        ),
        "court": "Supreme Court of California",
        "date_filed": "1973-06-04",
        "jurisdiction": "US",
        "url": "https://www.courtlistener.com/opinion/1177634/gruenberg-v-aetna-insurance-co/",
        "spotlight_brief": (
            "Gruenberg v. Aetna Insurance Co. holds that claim handling must reflect a genuine "
            "effort to pay covered benefits. Patterns of delay, repetitive document requests, "
            "and lowball offers without analysis can evidence bad faith in escalation-prone files."
        ),
        "spotlight_relevance": (
            "Supports proactive outreach on disputed high-value claims where communication "
            "tone is adversarial and the settlement gap remains large."
        ),
    },
]

_THEFT_CASES = [
    {
        "docid": "demo-us-montrose",
        "title": "Montrose Chemical Corp. v. Admiral Insurance Co.",
        "headline": "Coverage disputes turn on notice, policy wording, and timely insurer response.",
        "snippet": (
            "Leading California insurance coverage dispute addressing insurer duties when "
            "multiple claims and notice issues arise under complex liability policies."
        ),
        "court": "Supreme Court of California",
        "date_filed": "1995-12-28",
        "jurisdiction": "US",
        "url": "https://www.courtlistener.com/opinion/9551391/montrose-chemical-corp-v-admiral-insurance-co/",
        "spotlight_brief": (
            "Montrose Chemical Corp. v. Admiral Insurance Co. is a foundational California "
            "coverage dispute on insurer notice and handling of complex liability claims. "
            "For vehicle-theft and large-gap files, it underscores documenting notice timing, "
            "police reports, and the insurer's coverage position early."
        ),
        "spotlight_relevance": (
            "Applies to theft claims with disputed ACV/replacement cost and threatened legal "
            "action — prioritize documented notice analysis and senior sign-off on the denial path."
        ),
    },
    *_GENERAL_CASES[:2],
]

_BAD_FAITH_CASES = _GENERAL_CASES
