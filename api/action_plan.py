"""Generate structured adjuster action steps for the Recommended Action panel."""
import json
import os
import re
from typing import Any, Dict, List, Optional


def _rule_based_steps(
    claim_id: str,
    risk_pct: float,
    is_high_risk: bool,
    incident: str,
    trigger_phrases: Optional[List[dict]],
    top_warnings: Optional[List[str]],
) -> List[str]:
    steps: List[str] = []
    triggers = [p.get("phrase", "") for p in (trigger_phrases or [])[:4]]

    if is_high_risk or risk_pct >= 60:
        steps.append(
            f"Escalate to senior adjuster today — ML escalation risk is {risk_pct:.0f}% on claim {claim_id}."
        )
        steps.append(
            "Schedule a phone call with the claimant within 48 hours; document tone and commitments in the case file."
        )
    else:
        steps.append(
            f"Send a status update to the claimant confirming next milestones for claim {claim_id}."
        )

    if triggers:
        steps.append(
            f"Address detected trigger language ({', '.join(triggers[:3])}) — avoid delay and confirm a concrete timeline."
        )

    if top_warnings:
        steps.append(
            f"Review top risk drivers ({', '.join(top_warnings[:2])}) against policy limits and prior similar claims."
        )

    if incident and incident.lower() not in ("insurance", ""):
        steps.append(f"Pull precedent guidance for incident type: {incident}.")

    steps.append("Log all outreach in Salesforce (email + call) so RiskRadar rescoring includes latest activity.")

    return steps[:5]


def _parse_steps_from_text(text: str) -> List[str]:
    if not text:
        return []
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        m = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if m:
            lines.append(m.group(2).strip())
            continue
        m = re.match(r"^[-*•]\s+(.+)$", line)
        if m:
            lines.append(m.group(1).strip())
    if lines:
        return [re.sub(r"\*\*", "", s) for s in lines if len(s) > 10][:6]
    # fallback: split sentences
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [re.sub(r"\*\*", "", p).strip() for p in parts if len(p.strip()) > 15][:5]


def _build_prompt(
    claim_id: str,
    risk_pct: float,
    is_high_risk: bool,
    incident: str,
    trigger_phrases: Optional[List[dict]],
    top_warnings: Optional[List[str]],
    brief_excerpt: str = "",
) -> str:
    trigger_text = ", ".join([p.get("phrase", "") for p in (trigger_phrases or [])[:6]]) or "none"
    warnings_text = ", ".join(top_warnings or []) or "none"
    tone = "URGENT de-escalation" if is_high_risk else "standard professional"

    return f"""You are an expert insurance claims adjuster coach.

CLAIM: {claim_id}
Incident: {incident}
Escalation risk: {risk_pct:.1f}% ({'HIGH RISK' if is_high_risk else 'moderate/low'})
Trigger phrases: {trigger_text}
ML warning signs: {warnings_text}
Tone: {tone}

{f'Context from legal brief: {brief_excerpt[:400]}' if brief_excerpt else ''}

Write exactly 4 numbered action steps the adjuster should take TODAY.
Each step must be one sentence, specific, and actionable (who/what/when).
Do NOT write an email. Do NOT cite cases. No preamble.

Format (strict):
1. First step
2. Second step
3. Third step
4. Fourth step
"""


def generate_action_plan(
    claim_id: str,
    risk_pct: float,
    is_high_risk: bool,
    incident: str,
    trigger_phrases: Optional[List[dict]] = None,
    top_warnings: Optional[List[str]] = None,
    brief_text: str = "",
) -> Dict[str, Any]:
    """
    Returns { steps: string[], source: 'groq'|'gemini'|'rules' }
    """
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq

            client = Groq(api_key=groq_key)
            prompt = _build_prompt(
                claim_id, risk_pct, is_high_risk, incident,
                trigger_phrases, top_warnings, brief_text,
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=350,
            )
            raw = (resp.choices[0].message.content or "").strip()
            steps = _parse_steps_from_text(raw)
            if steps:
                return {"steps": steps, "source": "groq", "raw": raw}
        except Exception as e:
            print(f"[action_plan] Groq failed: {e}")

    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai

            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            prompt = _build_prompt(
                claim_id, risk_pct, is_high_risk, incident,
                trigger_phrases, top_warnings, brief_text,
            )
            resp = model.generate_content(prompt)
            raw = (resp.text or "").strip()
            steps = _parse_steps_from_text(raw)
            if steps:
                return {"steps": steps, "source": "gemini", "raw": raw}
        except Exception as e:
            print(f"[action_plan] Gemini failed: {e}")

    steps = _rule_based_steps(
        claim_id, risk_pct, is_high_risk, incident, trigger_phrases, top_warnings
    )
    return {"steps": steps, "source": "rules"}


def extract_from_brief(markdown: str | None) -> List[str]:
    """Pull steps from LLM brief sections (fallback for older responses)."""
    if not markdown:
        return []
    patterns = [
        r"(?:\*\*)?Strategic Action(?: Plan)?(?:\*\*)?\s*:?\s*([\s\S]*?)(?=\n\s*(?:\*\*)?[A-Z][A-Za-z ]{2,40}(?:\*\*)?\s*:|$)",
        r"(?:\*\*)?Recommended Next Step(?:s)?(?:\*\*)?\s*:?\s*([\s\S]*?)(?=\n\s*(?:\*\*)?[A-Z][A-Za-z ]{2,40}(?:\*\*)?\s*:|$)",
    ]
    for pat in patterns:
        m = re.search(pat, markdown, re.IGNORECASE)
        if m and m.group(1).strip():
            return _parse_steps_from_text(m.group(1).strip())
    return []
