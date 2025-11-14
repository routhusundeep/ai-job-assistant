"""High-level Gemini-powered flows."""

from __future__ import annotations

import json
import textwrap
from typing import Any, Dict, Optional

from .gemini import GeminiError, generate_gemini_content

DEFAULT_MODEL = "gemini-2.0-flash"


def run_fit_analysis(
    *,
    job: Dict[str, Any],
    resume_text: str,
    instructions: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Use Gemini to evaluate how well the resume matches the job."""

    prompt = _build_fit_prompt(job, resume_text, instructions)
    response = generate_gemini_content(prompt, model=model)
    payload = _safe_json_loads(response)
    summary = payload.get("summary") or payload.get("analysis") or response
    score = payload.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return {"summary": summary.strip(), "score": score}


def run_resume_tailoring(
    *,
    job: Dict[str, Any],
    resume_text: str,
    instructions: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Ask Gemini to tailor the resume text for the target job."""

    prompt = _build_resume_prompt(job, resume_text, instructions)
    content = generate_gemini_content(prompt, model=model)
    return {"content": content.strip()}


def run_outreach_generation(
    *,
    job: Dict[str, Any],
    resume_text: str,
    instructions: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Produce outreach email + LinkedIn message using Gemini."""

    prompt = _build_outreach_prompt(job, resume_text, instructions)
    response = generate_gemini_content(prompt, model=model)
    payload = _safe_json_loads(response)
    email = payload.get("email") or payload.get("email_text") or response
    linkedin = payload.get("linkedin") or payload.get("linkedin_message") or response
    return {"email": email.strip(), "linkedin": linkedin.strip()}


def _build_fit_prompt(job: Dict[str, Any], resume_text: str, instructions: Optional[str]) -> str:
    details = textwrap.dedent(
        f"""
        Job Title: {job['title']}
        Company: {job['company']}
        Description:\n{job['description']}
        Existing Vector Score: {job.get('score')}
        Existing LLM Score: {job.get('llm_refined_score')}
        """
    ).strip()
    guidance = "Evaluate how well the resume fits the job (0-1)."
    if instructions:
        guidance += f"\nUser instructions: {instructions.strip()}"
    return textwrap.dedent(
        f"""
        You are a meticulous career coach.
        Compare the provided resume with the job details and respond with JSON in the form:
        {{"score": <0-1 float>, "summary": "3-4 sentence assessment"}}.
        Be honest. Do not fabricate skills.

        Resume:\n{resume_text}

        Job Details:\n{details}

        {guidance}
        """
    ).strip()


def _build_resume_prompt(job: Dict[str, Any], resume_text: str, instructions: Optional[str]) -> str:
    base_rules = (
        "Tailor the resume for the specific job while keeping it to a single page, "
        "preserving truthful experience, and avoiding exaggerated or new skills."
    )
    extra = f"\nCustom instructions: {instructions.strip()}" if instructions else ""
    return textwrap.dedent(
        f"""
        You are an expert resume writer.
        Rewrite the following resume to better target the job below.
        Output the full resume text (plain text or Markdown) ready to copy-paste.
        {base_rules}{extra}

        Current Resume:\n{resume_text}

        Target Job:\nTitle: {job['title']}
Company: {job['company']}
Description:\n{job['description']}
        """
    ).strip()


def _build_outreach_prompt(job: Dict[str, Any], resume_text: str, instructions: Optional[str]) -> str:
    extra = f"\nCustom instructions: {instructions.strip()}" if instructions else ""
    recruiter_line = (
        f"You may reference recruiter profile: {job['recruiter_url']}."
        if job.get("recruiter_url")
        else ""
    )
    return textwrap.dedent(
        f"""
        Craft concise, professional outreach for the job below.
        Respond with JSON: {{"email": "...", "linkedin": "..."}}.
        Email should be 3 short paragraphs max. LinkedIn message should be friendly and < 500 characters.
        Highlight genuine alignment; do not invent new skills. Reference the resume only when relevant.
        {recruiter_line}{extra}

        Resume Summary:\n{resume_text[:2000]}

        Job Details:\nTitle: {job['title']}
Company: {job['company']}
Description:\n{job['description']}
        """
    ).strip()


def _safe_json_loads(payload: str) -> Dict[str, Any]:
    payload = payload.strip()
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        # Attempt to locate JSON substring
        start = payload.find("{")
        end = payload.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = payload[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return {"summary": payload}
        return {"summary": payload}
