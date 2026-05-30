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

load_dotenv()

MAX_CASES_IN_PROMPT = 6
MAX_HEADLINE_CHARS = 180


def _clean_title(t):
    if not t:
        return ""
    return re.sub(r"\s+", " ", str(t)).strip()


def _format_case_block(cases):
    """Compact, citation-ready list of retrieved precedents."""
    lines = []
    for i, c in enumerate(cases[:MAX_CASES_IN_PROMPT], 1):
        title = _clean_title(c.get("title") or c.get("name") or f"Case {i}")
        jur = c.get("jurisdiction", "Unknown")
        headline = _clean_title(c.get("headline") or c.get("snippet") or "")
        if headline and len(headline) > MAX_HEADLINE_CHARS:
            headline = headline[:MAX_HEADLINE_CHARS].rstrip() + "..."
        line = f"  [{i}] {title}  ({jur})"
        if headline:
            line += f"\n      Excerpt: {headline}"
        lines.append(line)
    if not lines:
        return "  (no precedents retrieved — do NOT invent any)"
    return "\n".join(lines)


def _allowed_titles(cases):
    return [_clean_title(c.get("title") or c.get("name") or "") for c in cases[:MAX_CASES_IN_PROMPT]]


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
            self.gemini = genai.GenerativeModel("gemini-1.5-flash")
        else:
            self.gemini = None

        groq_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_key) if groq_key else None

    def _build_prompt(self, data, judgements):
        risk = round(float(data.get("risk_score_pct", 0)), 1)
        flags = data.get("top_warning_signs", []) or []
        cases = judgements or []
        allowed = _allowed_titles(cases)
        case_block = _format_case_block(cases)

        has_india = any(c.get("jurisdiction") == "India" for c in cases)
        has_us = any(c.get("jurisdiction") == "US" for c in cases)
        if has_india and has_us:
            persona = "Global Insurance Claims Strategist"
        elif has_us:
            persona = "US Insurance Claims Strategist"
        else:
            persona = "Expert Insurance Claims Strategist (India)"

        return f"""ROLE: {persona}

CLAIM SNAPSHOT:
  Escalation risk score: {risk}%
  Top risk signals: {flags}

RETRIEVED PRECEDENTS (the only precedents you may cite):
{case_block}

STRICT CITATION RULES (follow exactly):
  1. If you reference a precedent, use the format [Case: <exact title as shown above>].
  2. Do NOT invent, paraphrase, or introduce any case not in the RETRIEVED PRECEDENTS list above.
  3. If no retrieved precedents apply, say so plainly — do NOT fabricate one.
  4. Stay within {len(allowed) if allowed else 0} cases. Prefer the single strongest match.

TASK: Write a ~120 word consensus brief for the adjuster, structured as:
  1. **Risk Summary** — justify the {risk}% score using the risk signals.
  2. **Legal Impact** — cite at most two retrieved precedents in [Case: ...] form and explain how they shape liability on this claim.
  3. **Recommended Next Step** — one concrete action the adjuster should take today.

Tone: professional, decisive, specific. No hedging phrases like 'it depends'.
"""

    def generate_all(self, data, judgements):
        prompt = self._build_prompt(data, judgements)
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
                        max_output_tokens=400,
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
                    max_tokens=400,
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
