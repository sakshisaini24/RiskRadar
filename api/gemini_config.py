"""Shared Gemini model name, generation config, and response parsing.

Supports google-generativeai 0.8.x (no thinking_config) and 0.9+/1.x (thinking_config).
"""
import os
from typing import Any

# gemini-1.5-flash / gemini-2.0-flash are 404 for many new API keys (2025+).
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def gemini_model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


def _safe_generation_config(max_output_tokens: int):
    """
    Returns a GenerationConfig object.

    On Gemini 2.5+ the model burns 'thinking' tokens against max_output_tokens
    by default, leaving almost nothing for the visible answer.  Setting
    thinking_budget=0 fixes this, but the field only exists in SDK >= 0.9.
    We try it first and fall back to a plain config when the SDK is older.
    """
    import google.generativeai as genai  # imported lazily to avoid startup cost

    base = dict(temperature=0.0, top_p=1.0, max_output_tokens=max_output_tokens)

    # Try dict-style (works on newer SDK builds that accept unknown kwargs)
    for extra in ({"thinking_config": {"thinking_budget": 0}}, {}):
        try:
            cfg = genai.types.GenerationConfig(**base, **extra)
            return cfg
        except (TypeError, ValueError):
            pass  # unknown field – try without

    return genai.types.GenerationConfig(**base)


def extract_gemini_text(response: Any) -> str:
    """Extract the visible answer from a generate_content response."""
    if response is None:
        return ""
    # Fast path – works on most SDK versions
    try:
        text = (response.text or "").strip()
        if text:
            return text
    except (ValueError, AttributeError):
        pass

    # Slow path – iterate candidates/parts, skip internal 'thought' parts
    chunks: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            t = getattr(part, "text", None)
            if t:
                chunks.append(str(t).strip())
    return "\n".join(chunks).strip()


def generate_gemini_text(model, prompt: str, max_output_tokens: int = 1024) -> str:
    """
    Call model.generate_content with thinking disabled where possible.
    Retries once with 2× the token budget if the response looks too short.
    """
    text = ""
    for budget in (max_output_tokens, max_output_tokens * 2):
        try:
            res = model.generate_content(
                prompt,
                generation_config=_safe_generation_config(budget),
            )
            text = extract_gemini_text(res)
        except Exception as exc:
            raise exc  # let callers catch and label the error properly
        if len(text) >= 80:
            return text
    return text
