"""Generates drafted next-action emails for the adjuster to send to the claimant."""
import os
import re
import json


def _build_prompt(claim_id, risk_pct, is_high_risk, incident, trigger_phrases, top_warnings, email_excerpt):
    trigger_text = ", ".join([p["phrase"] for p in (trigger_phrases or [])[:6]]) or "none detected"
    warnings_text = ", ".join(top_warnings or []) or "none"
    excerpt = (email_excerpt or "").strip()[:600] or "(no recent claimant email)"

    tone_guidance = (
        "URGENT DE-ESCALATION TONE: acknowledge the claimant's frustration empathetically, "
        "commit to a concrete next step within 48 hours, avoid admitting liability, "
        "offer a specific communication channel (phone call)."
        if is_high_risk
        else "STANDARD PROFESSIONAL TONE: confirm progress, provide clarity on timelines, "
             "thank them for cooperation, keep brief."
    )

    return f"""You are an expert insurance claims adjuster. Draft a single email to the claimant.

CLAIM CONTEXT:
- Claim ID: {claim_id}
- Incident: {incident}
- Escalation risk: {risk_pct:.1f}%{" (HIGH RISK)" if is_high_risk else ""}
- Detected trigger phrases in prior communication: {trigger_text}
- Top risk warnings: {warnings_text}

RECENT CLAIMANT EMAIL EXCERPT:
\"\"\"
{excerpt}
\"\"\"

{tone_guidance}

REQUIREMENTS:
- Write ONLY the email. Do NOT include preamble, explanations, or disclaimers.
- Start with "Subject: " on the first line.
- Follow with greeting, body (2-4 short paragraphs), sign-off.
- Sign as "[Adjuster Name], Claims Adjuster". Do NOT invent a real adjuster name.
- Reference the claim ID naturally.
- Word count: 120-220 words.
- No markdown formatting. Plain text only.

Output ONLY the email text."""


def _parse_email(text):
    """Extract subject + body from a plain-text email."""
    if not text:
        return None
    text = text.strip()
    lines = text.split("\n")
    subject = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return {"subject": subject or "(no subject)", "body": body}


def generate_groq_email(client_factory, **kwargs):
    try:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return {"error": "GROQ_API_KEY not configured"}
        from groq import Groq
        client = Groq(api_key=groq_key)
        prompt = _build_prompt(**kwargs)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.4,
        )
        raw = resp.choices[0].message.content.strip()
        parsed = _parse_email(raw)
        if not parsed:
            return {"error": "empty response"}
        return {"subject": parsed["subject"], "body": parsed["body"], "model": "Groq Llama 3.3"}
    except Exception as e:
        return {"error": f"Groq: {str(e)[:150]}"}


def generate_gemini_email(**kwargs):
    try:
        gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            return {"error": "GOOGLE_API_KEY not configured"}
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        from api.gemini_config import gemini_model_name

        model = genai.GenerativeModel(gemini_model_name())
        prompt = _build_prompt(**kwargs)
        resp = model.generate_content(prompt)
        raw = (resp.text or "").strip()
        parsed = _parse_email(raw)
        if not parsed:
            return {"error": "empty response"}
        return {"subject": parsed["subject"], "body": parsed["body"], "model": "Gemini 2.5 Flash"}
    except Exception as e:
        return {"error": f"Gemini: {str(e)[:150]}"}


def generate_emails(claim_id, risk_pct, is_high_risk, incident, trigger_phrases, top_warnings, email_excerpt):
    """Returns both Groq and Gemini drafts."""
    kwargs = dict(
        claim_id=claim_id,
        risk_pct=risk_pct,
        is_high_risk=is_high_risk,
        incident=incident,
        trigger_phrases=trigger_phrases,
        top_warnings=top_warnings,
        email_excerpt=email_excerpt,
    )
    return {
        "groq": generate_groq_email(None, **kwargs),
        "gemini": generate_gemini_email(**kwargs),
    }