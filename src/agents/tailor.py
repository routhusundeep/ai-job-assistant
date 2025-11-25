"""Agentic resume tailoring that preserves LaTeX structure and enforces one-page output."""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from PyPDF2 import PdfReader

from .gemini import generate_gemini_content
from ..tools.render_resume import render_resume

MAX_ITERATIONS = 5
VERSIONS_DIR = Path("data/versions")
LOGGER = logging.getLogger(__name__)


def _extract_code_block(text: str) -> str:
    """Strip fences and return raw TeX."""
    fenced = re.search(r"```(?:tex|latex)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def _build_tailor_prompt(
    job: Dict[str, Any], base_tex: str, instructions: Optional[str], feedback: Optional[str]
) -> str:
    constraint_lines = [
        "Keep the LaTeX structure and macros exactly as-is. Do not add packages or change class/structure.",
        "Do not invent new facts, skills, roles, or dates. Only rephrase or reorder existing content.",
        "Target a single page; shorten text as needed while preserving truthfulness.",
        "Return the full modified LaTeX document only (no commentary).",
    ]
    if feedback:
        constraint_lines.append(f"Additional adjustments: {feedback}")
    base_guidance = "\n".join(f"- {line}" for line in constraint_lines)
    job_block = f"Title: {job['title']}\nCompany: {job['company']}\nDescription:\n{job['description']}"
    user_instructions = instructions.strip() if instructions else ""
    prompt = (
        "You are tailoring a resume by editing LaTeX content only.\n\n"
        f"Job details:\n{job_block}\n\n"
        f"Constraints:\n{base_guidance}\n"
    )
    if user_instructions:
        prompt += f"\nUser instructions:\n{user_instructions}\n"
    prompt += "\nHere is the current LaTeX. Return the full modified LaTeX:\n"
    prompt += base_tex
    return prompt


def _count_pages(pdf_path: Path) -> int:
    reader = PdfReader(pdf_path)
    return len(reader.pages)


def tailor_resume_agentic(
    *,
    job: Dict[str, Any],
    master_tex_path: Path,
    class_path: Path,
    instructions: Optional[str],
) -> Dict[str, Any]:
    """Iteratively tailor the resume LaTeX and enforce one-page PDF."""
    if not master_tex_path.exists():
        raise FileNotFoundError(f"Master resume not found at {master_tex_path}")
    if not class_path.exists():
        raise FileNotFoundError(f"Class file not found at {class_path}")

    base_tex = master_tex_path.read_text(encoding="utf-8")
    feedback: Optional[str] = None
    attempt_tex = base_tex
    page_count = None
    status = "failed"
    last_error: Optional[str] = None

    stale_paths = []

    for _ in range(MAX_ITERATIONS):
        prompt = _build_tailor_prompt(job, attempt_tex, instructions, feedback)
        response = generate_gemini_content(prompt)
        candidate_tex = _extract_code_block(response)

        VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        temp_id = uuid4().hex
        temp_tex_path = VERSIONS_DIR / f"{temp_id}.tex"
        temp_pdf_path = VERSIONS_DIR / f"{temp_id}.pdf"
        temp_tex_path.write_text(candidate_tex, encoding="utf-8")

        try:
            rendered_pdf = render_resume(
                tex_path=temp_tex_path,
                cls_path=class_path,
                output_pdf=temp_pdf_path,
                keep_aux=False,
            )
            page_count = _count_pages(rendered_pdf)
        except Exception as exc:  # capture compile errors and retry
            last_error = str(exc)
            feedback = (
                "The previous LaTeX failed to compile. Fix the LaTeX syntax without changing structure "
                "or adding packages. Do not use alignment tabs (&) unless inside proper tables. "
                f"Compiler message: {last_error[:500]}"
            )
            attempt_tex = candidate_tex
            stale_paths.append((temp_tex_path, temp_pdf_path))
            LOGGER.debug("Tailor compile failed: %s", last_error)
            continue

        if page_count <= 1:
            status = "success"
            version_id = temp_id
            for old_tex, old_pdf in stale_paths:
                for path in (old_tex, old_pdf):
                    try:
                        path.unlink()
                    except OSError:
                        continue
            return {
                "version_id": version_id,
                "tex_path": temp_tex_path,
                "pdf_path": temp_pdf_path,
                "page_count": page_count,
                "status": status,
            }

        feedback = (
            f"Current PDF is {page_count} pages. Reduce to a single page without adding facts. "
            "Shorten bullet text and keep structure identical."
        )
        attempt_tex = candidate_tex
        stale_paths.append((temp_tex_path, temp_pdf_path))

    # If loop exits without success, return last attempt info
    version_id = temp_id
    status = "failed_compile" if last_error else status
    return {
        "version_id": version_id,
        "tex_path": temp_tex_path,
        "pdf_path": temp_pdf_path,
        "page_count": page_count,
        "status": status,
        "error": last_error,
    }
