"""
Grounded LLM brief generator.

Both Gemini and Groq are called with temperature=0 and a prompt that
forces citations in [Case: <exact title>] format drawn from an allowlist
of retrieved precedents. After generation, every citation is validated
against that allowlist — any citation outside the list is flagged as an
unsupported claim so the UI can badge it visibly.
"""
import os
import re
import google.generativeai as genai
from groq import Groq
from dotenv import load_dotenv

from api.gemini_config import gemini_model_name

load_dotenv()

MAX_CASES_IN_PROMPT = 6
MAX_HEADLINE_CHARS = 180


def _clean_title(t):
    if not t:
        return ""
    return re.sub(r"\s+", " ", str(t)).strip()


def order_precedents_for_brief(cases):
    """US precedents first so Legal Impact leads with primary US authority."""
    if not cases:
        return []
    us = [c for c in cases if str(c.get("jurisdiction", "")).upper() == "US"]
    india = [c for c in cases if str(c.get("jurisdiction", "")).lower() == "india"]
    other = [c for c in cases if c not in us and c not in india]
    ordered = us[:3] + india[:3] + other
    return ordered[:MAX_CASES_IN_PROMPT]


def _format_case_block(cases):
    """Compact, citation-ready list — US block before India."""
    ordered = order_precedents_for_brief(cases)
    if not ordered:
        return "  (no precedents retrieved — do NOT invent any)"

    us = [c for c in ordered if str(c.get("jurisdiction", "")).upper() == "US"]
    india = [c for c in ordered if str(c.get("jurisdiction", "")).lower() == "india"]
    lines = []

    def _append_group(label, group, start_idx):
        if not group:
            return start_idx
        lines.append(f"  {label}")
        idx = start_idx
        for c in group:
            title = _clean_title(c.get("title") or c.get("name") or f"Case {idx}")
            headline = _clean_title(c.get("headline") or c.get("snippet") or "")
            if headline and len(headline) > MAX_HEADLINE_CHARS:
                headline = headline[:MAX_HEADLINE_CHARS].rstrip() + "..."
            line = f"  [{idx}] {title}  (US)" if label.startswith("PRIMARY") else f"  [{idx}] {title}  (India)"
            if headline:
                line += f"\n      Excerpt: {headline}"
            rel = c.get("relevance_note")
            if rel:
                line += f"\n      Why retrieved: {rel}"
            lines.append(line)
            idx += 1
        return idx

    n = 1
    n = _append_group("PRIMARY US PRECEDENTS (cite first in Legal Impact):", us, n)
    _append_group("SECONDARY INDIA PRECEDENTS (cite second):", india, n)
    return "\n".join(lines)


def _allowed_titles(cases):
    return [
        _clean_title(c.get("title") or c.get("name") or "")
        for c in order_precedents_for_brief(cases)
    ]


def validate_citations(text, allowed_titles):
    """
    Extract every [Case: X] reference in the text and check each against
    the allowed list. Returns (citations_found, unsupported_citations).

    A citation is "supported" if the cited title overlaps >=60% of tokens
    with any allowed title (case-insensitive). This accommodates the LLM
    shortening "Foo Insurance v. Bar Corp (2021)" to "Foo v. Bar".
    """
    if not text:
        return [], []
    pattern = re.compile(r"\[Case:\s*([^\]]+)\]", re.IGNORECASE)
    cited = [m.strip() for m in pattern.findall(text)]
    if not cited:
        return [], []

    allowed_norm = [set(re.findall(r"\w+", t.lower())) for t in allowed_titles if t]
    unsupported = []
    for c in cited:
        c_tokens = set(re.findall(r"\w+", c.lower()))
        if not c_tokens:
            continue
        supported = False
        for a_tokens in allowed_norm:
            if not a_tokens:
                continue
            overlap = len(c_tokens & a_tokens) / max(len(c_tokens), 1)
            if overlap >= 0.6:
                supported = True
                break
        if not supported:
            unsupported.append(c)
    return cited, unsupported


class BriefGenerator:
    def __init__(self):
        google_key = os.getenv("GEMINI_API_KEY")
        if google_key:
            genai.configure(api_key=google_key)
            self.gemini = genai.GenerativeModel(gemini_model_name())
        else:
            self.gemini = None

        groq_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_key) if groq_key else None

    def _build_prompt(self, data, judgements, claim_context=None):
        risk = round(float(data.get("risk_score_pct", 0)), 1)
        flags = data.get("top_warning_signs", []) or []
        ordered = order_precedents_for_brief(judgements or [])
        allowed = _allowed_titles(ordered)
        case_block = _format_case_block(judgements or [])

        ctx = claim_context or {}
        incident = ctx.get("incident_type") or "insurance claim"
        claim_id = ctx.get("claim_id") or ""

        has_india = any(str(c.get("jurisdiction", "")).lower() == "india" for c in ordered)
        has_us = any(str(c.get("jurisdiction", "")).upper() == "US" for c in ordered)
        if has_india and has_us:
            persona = "Global Insurance Claims Strategist (US primary, India secondary)"
        elif has_us:
            persona = "US Insurance Claims Strategist"
        else:
            persona = "Expert Insurance Claims Strategist (India)"

        legal_impact_rules = (
            "2. **Legal Impact** — use this exact structure:\n"
            "   **US precedent:** One sentence with [Case: <exact US title>] stating how that decision "
            "applies to this claim's facts (coverage, bad faith, notice, or liability).\n"
            "   **India precedent:** One sentence with [Case: <exact India title>] stating the parallel "
            "duty, notice, or liability principle for this claim.\n"
            "   If no US precedent is listed, omit the US line. If no India precedent is listed, omit the India line.\n"
            "   Always cite US before India when both exist."
        )
        if has_us and not has_india:
            legal_impact_rules = (
                "2. **Legal Impact** — one or two sentences citing [Case: <exact US title>] and explaining "
                "how the decision applies to this claim."
            )
        elif has_india and not has_us:
            legal_impact_rules = (
                "2. **Legal Impact** — one or two sentences citing [Case: <exact India title>] and explaining "
                "how the decision applies to this claim."
            )

        return f"""ROLE: {persona}

CLAIM SNAPSHOT:
  Claim ID: {claim_id}
  Incident type: {incident}
  Escalation risk score: {risk}%
  Top risk signals: {flags}

RETRIEVED PRECEDENTS (the only precedents you may cite):
{case_block}

STRICT CITATION RULES (follow exactly):
  1. Use [Case: <exact title as shown above>] for every precedent reference.
  2. Do NOT invent cases. Do NOT use outside knowledge of cases not listed above.
  3. Do NOT use hedging words: likely, probably, may have, might, possibly, appears to.
  4. Write as if summarizing retrieved excerpts — state principles directly.

TASK: Write ~140 words for the adjuster:
  1. **Risk Summary** — justify the {risk}% score using the risk signals (2 sentences max).
{legal_impact_rules}
  3. **Recommended Next Step** — one concrete action for today.

Tone: professional, decisive, specific.
"""

    def generate_all(self, data, judgements, claim_context=None):
        prompt = self._build_prompt(data, judgements, claim_context=claim_context)
        allowed = _allowed_titles(judgements or [])
        responses = {}

        # Google Gemini
        try:
            if self.gemini:
                res = self.gemini.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.0,
                        top_p=1.0,
                        max_output_tokens=500,
                    ),
                )
                text = (res.text or "").strip()
                cited, unsupported = validate_citations(text, allowed)
                responses["google_gemini"] = text
                responses["google_gemini_grounding"] = {
                    "citations_found": cited,
                    "unsupported_citations": unsupported,
                    "temperature": 0.0,
                    "allowed_cases": allowed,
                }
            else:
                responses["google_gemini"] = "Gemini Key Missing"
                responses["google_gemini_grounding"] = None
        except Exception as e:
            responses["google_gemini"] = f"Gemini Error: {str(e)}"
            responses["google_gemini_grounding"] = None

        # Groq (Llama)
        try:
            if self.groq_client:
                res = self.groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    top_p=1.0,
                    max_tokens=500,
                )
                text = res.choices[0].message.content.strip()
                cited, unsupported = validate_citations(text, allowed)
                responses["groq_llama"] = text
                responses["groq_llama_grounding"] = {
                    "citations_found": cited,
                    "unsupported_citations": unsupported,
                    "temperature": 0.0,
                    "allowed_cases": allowed,
                }
            else:
                responses["groq_llama"] = "Groq Key Missing"
                responses["groq_llama_grounding"] = None
        except Exception as e:
            responses["groq_llama"] = f"Groq Error: {str(e)}"
            responses["groq_llama_grounding"] = None

        return responses
