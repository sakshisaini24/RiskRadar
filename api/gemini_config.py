"""Shared Gemini model id (override via GEMINI_MODEL in .env)."""
import os

# gemini-1.5-flash and gemini-2.0-flash return 404 for many new API keys (2025+).
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def gemini_model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
