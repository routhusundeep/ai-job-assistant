"""Optional LLM-based reranking for job similarity scores."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankedJob:
    """Container for jobs sent to an LLM for refinement."""

    job_id: str
    description: str
    score: float


def _serialize_jobs(jobs: Iterable[RankedJob]) -> str:
    """Create a compact JSON payload for the prompt."""
    payload = [
        {"job_id": job.job_id, "score": job.score, "description": job.description}
        for job in jobs
    ]
    return json.dumps(payload, ensure_ascii=False)


def _build_prompt(jobs: Iterable[RankedJob]) -> str:
    """Construct a consistent instruction for Gemini/GPT models."""
    serialized = _serialize_jobs(jobs)
    return (
        "You are re-ranking job descriptions for resume alignment. "
        "Given the JSON array of jobs below (each with job_id, score, description) "
        "return a JSON array of objects where each object contains job_id and "
        "refined_score between 0 and 1. Higher is better. Respond with JSON only.\n"
        f"Jobs: {serialized}"
    )


def _refine_with_gemini(jobs: List[RankedJob], model_name: Optional[str]) -> Dict[str, float]:
    """Use Gemini to refine ranking, returning job_id to refined score."""
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        LOGGER.warning("google-generativeai package not installed; skipping Gemini refinement.")
        return {}

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        LOGGER.warning("GOOGLE_API_KEY not set; skipping Gemini refinement.")
        return {}

    genai.configure(api_key=api_key)
    model_id = model_name or "gemini-1.5-flash"
    prompt = _build_prompt(jobs)

    try:
        model = genai.GenerativeModel(model_id)
        response = model.generate_content(prompt)
        text = response.text or ""
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("Gemini refinement failed: %s", exc)
        return {}

    return _parse_refined_scores(text)


def _refine_with_openai(jobs: List[RankedJob], model_name: Optional[str]) -> Dict[str, float]:
    """Use the OpenAI client to refine the ranking."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        LOGGER.warning("openai package not installed; skipping GPT refinement.")
        return {}

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        LOGGER.warning("OPENAI_API_KEY not set; skipping GPT refinement.")
        return {}

    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(jobs)
    model_id = model_name or "gpt-4.1-mini"

    try:
        response = client.responses.create(model=model_id, input=prompt, temperature=0.1)
        text = response.output_text or ""
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("OpenAI refinement failed: %s", exc)
        return {}

    return _parse_refined_scores(text)


def _parse_refined_scores(response_text: str) -> Dict[str, float]:
    """Parse refined scores JSON emitted by an LLM."""
    response_text = response_text.strip()
    if not response_text:
        return {}

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        LOGGER.error("Failed to decode LLM refinement payload: %s", response_text)
        return {}

    refined: Dict[str, float] = {}
    for entry in payload:
        job_id = entry.get("job_id")
        score = entry.get("refined_score")
        if not job_id:
            continue
        try:
            refined[job_id] = float(score)
        except (TypeError, ValueError):
            LOGGER.debug("Skipping invalid refined score for job_id %s: %s", job_id, score)
            continue
    return refined


def refine_scores(
    jobs: List[RankedJob],
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Dict[str, float]:
    """Refine similarity scores using an LLM if configured.

    Args:
        jobs: Top candidate jobs sorted by similarity.
        provider: Optional explicit provider, e.g. 'gemini' or 'openai'.
        model_name: Optional override for the downstream LLM model id.

    Returns:
        Mapping of job_id to refined score. Empty if refinement skipped.
    """
    if not jobs:
        return {}

    normalized_provider = (provider or "").lower()

    if normalized_provider not in {"gemini", "openai", ""}:
        LOGGER.warning("Unknown LLM provider %s; skipping refinement.", provider)
        return {}

    if normalized_provider == "gemini":
        return _refine_with_gemini(jobs, model_name)

    if normalized_provider == "openai":
        return _refine_with_openai(jobs, model_name)

    # Auto-detect provider preference.
    if os.environ.get("GOOGLE_API_KEY"):
        return _refine_with_gemini(jobs, model_name)
    if os.environ.get("OPENAI_API_KEY"):
        return _refine_with_openai(jobs, model_name)

    LOGGER.warning("LLM refinement requested but no provider configured; skipping.")
    return {}
