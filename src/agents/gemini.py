"""Utility wrapper around the google-genai client."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


class GeminiError(RuntimeError):
    """Raised when Gemini calls fail or configuration is missing."""


@lru_cache(maxsize=1)
def _load_client():
    try:
        from google import genai  # type: ignore
    except ImportError as exc:  # pragma: no cover - import error bubble up
        raise GeminiError(
            "google-genai package is not installed. Install requirements.txt."
        ) from exc

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise GeminiError("GOOGLE_API_KEY environment variable is not set.")

    return genai.Client(api_key=api_key)


def generate_gemini_content(
    prompt: str,
    *,
    model: str = "gemini-2.5-flash",
    system_instruction: Optional[str] = None,
) -> str:
    """Send a single prompt to Gemini and return the text response."""

    client = _load_client()
    contents = prompt if not system_instruction else f"{system_instruction}\n\n{prompt}"

    try:
        response = client.models.generate_content(model=model, contents=contents)
    except Exception as exc:  # pragma: no cover - upstream SDK errors
        raise GeminiError(f"Gemini request failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not text:
        raise GeminiError("Gemini returned an empty response.")
    return text.strip()
