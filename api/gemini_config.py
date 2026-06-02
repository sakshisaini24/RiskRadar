"""Shared Gemini model id, generation config, and response parsing."""
import os
from typing import Any

# gemini-1.5-flash / gemini-2.0-flash often 404 on new API keys (2025+).
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def gemini_model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


def gemini_generation_config(max_output_tokens: int = 1024):
    """
    GenerationConfig for briefs/emails.

    Gemini 2.5+ spends thinking tokens against max_output_tokens by default,
    which truncates visible output (e.g. only 'Risk Summary: ... justified by').
    thinking_budget=0 sends the full budget to the answer.
    """
    import google.generativeai as genai

    base = {
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": max_output_tokens,
    }
    # Dict form works on recent google-generativeai; disables 2.5 "thinking" token drain.
    for extra in (
        {"thinking_config": {"thinking_budget": 0}},
        {},
    ):
        try:
            return genai.types.GenerationConfig(**base, **extra)
        except (TypeError, ValueError):
            continue
        try:
            thinking_cls = getattr(genai.types, "ThinkingConfig", None)
            if thinking_cls and extra:
                return genai.types.GenerationConfig(
                    **base,
                    thinking_config=thinking_cls(thinking_budget=0),
                )
        except (AttributeError, TypeError, ValueError):
            continue
    return genai.types.GenerationConfig(**base)


def extract_gemini_text(response: Any) -> str:
    """Extract visible answer text from generate_content (not thinking parts)."""
    if response is None:
        return ""
    try:
        text = (response.text or "").strip()
        if text:
            return text
    except (ValueError, AttributeError):
        pass

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


def _generation_config_dict(max_output_tokens: int) -> dict:
    return {
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": max_output_tokens,
        "thinking_config": {"thinking_budget": 0},
    }


def generate_gemini_text(model, prompt: str, max_output_tokens: int = 1024) -> str:
    """Call Gemini with thinking disabled; retry once if output is too short."""
    text = ""
    for budget in (max_output_tokens, max_output_tokens * 2):
        res = model.generate_content(
            prompt,
            generation_config=_generation_config_dict(budget),
        )
        text = extract_gemini_text(res)
        if len(text) >= 80:
            return text
    return text
