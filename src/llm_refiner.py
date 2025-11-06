"""Optional LLM-based reranking for job similarity scores."""

from __future__ import annotations

import json
import logging
import os
import re
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


def _refine_with_ollama(
    jobs: List[RankedJob], model_name: Optional[str]
) -> Dict[str, float]:
    """Use a local Ollama model to refine ranking."""
    try:
        import ollama  # type: ignore
    except ImportError:
        LOGGER.warning("ollama package not installed; skipping local rerank.")
        return {}

    prompt = _build_prompt(jobs)
    model_id = model_name or "phi3"

    LOGGER.debug("Ollama refinement request (%s): %s", model_id, prompt)
    messages = [
        {
            "role": "system",
            "content": (
                "You re-rank job descriptions based on how well they match the resume. "
                "Respond with a JSON array containing objects with job_id and refined_score (0-1)."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = ollama.chat(model=model_id, messages=messages)  # type: ignore[arg-type]
        text = response.get("message", {}).get("content", "")
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("Ollama refinement failed: %s", exc)
        return {}

    LOGGER.debug("Ollama refinement response: %s", text)
    return _parse_refined_scores(text)


def _refine_with_gemini(
    jobs: List[RankedJob], model_name: Optional[str]
) -> Dict[str, float]:
    """Use Gemini to refine ranking, returning job_id to refined score."""
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        LOGGER.warning(
            "google-generativeai package not installed; skipping Gemini refinement."
        )
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


def _refine_with_openai(
    jobs: List[RankedJob], model_name: Optional[str]
) -> Dict[str, float]:
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
        response = client.responses.create(
            model=model_id, input=prompt, temperature=0.1
        )
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
        return _parse_relaxed_scores(response_text)

    refined: Dict[str, float] = {}
    for entry in payload:
        job_id = entry.get("job_id")
        score = entry.get("refined_score")
        if not job_id:
            continue
        try:
            refined[job_id] = float(score)
        except (TypeError, ValueError):
            LOGGER.debug(
                "Skipping invalid refined score for job_id %s: %s", job_id, score
            )
            continue
    return refined


def _parse_relaxed_scores(response_text: str) -> Dict[str, float]:
    """Fallback parser that tolerates loosely formatted JSON-like payloads."""
    pattern = re.compile(
        r'"job_id"\s*:\s*"(?P<job_id>[^"]+)"[^}]*?"refined_score"\s*:\s*(?P<score>[^,\}\]]+)',
        re.IGNORECASE | re.DOTALL,
    )
    refined: Dict[str, float] = {}

    for match in pattern.finditer(response_text):
        job_id = match.group("job_id").strip()
        score_raw = match.group("score").strip()
        if not job_id or not score_raw:
            continue

        normalized = score_raw.strip('"')
        if normalized.lower() in {"nan", "none"}:
            LOGGER.debug(
                "Skipping non-numeric refined score for job_id %s: %s", job_id, score_raw
            )
            continue

        if re.fullmatch(r"0+", normalized):
            normalized = "0"
        elif re.fullmatch(r"0+[0-9]+(\.[0-9]+)?", normalized):
            normalized = normalized.lstrip("0")
            if normalized.startswith("."):
                normalized = f"0{normalized}"

        try:
            refined[job_id] = float(normalized)
        except ValueError:
            LOGGER.debug(
                "Skipping refined score that could not be coerced for job_id %s: %s",
                job_id,
                score_raw,
            )
            continue

    if not refined:
        LOGGER.warning("Relaxed parsing failed for LLM payload: %s", response_text)
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

    if normalized_provider not in {"gemini", "openai", "ollama", ""}:
        LOGGER.warning("Unknown LLM provider %s; skipping refinement.", provider)
        return {}

    if normalized_provider == "ollama":
        return _refine_with_ollama(jobs, model_name)

    if normalized_provider == "gemini":
        return _refine_with_gemini(jobs, model_name)

    if normalized_provider == "openai":
        return _refine_with_openai(jobs, model_name)

    # Auto-detect provider preference.
    local_result = _refine_with_ollama(jobs, model_name)
    if local_result:
        return local_result

    if os.environ.get("GOOGLE_API_KEY"):
        return _refine_with_gemini(jobs, model_name)
    if os.environ.get("OPENAI_API_KEY"):
        return _refine_with_openai(jobs, model_name)

    LOGGER.warning("LLM refinement requested but no provider configured; skipping.")
    return {}
