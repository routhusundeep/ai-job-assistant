"""Helpers for loading the master resume."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from PyPDF2 import PdfReader

DEFAULT_RESUME_PATH = Path("data/resume.pdf")


@lru_cache(maxsize=1)
def load_master_resume_text(resume_path: Optional[Path] = None) -> str:
    """Load the text content from the master resume PDF."""

    path = resume_path or DEFAULT_RESUME_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Master resume not found at {path}. Ensure data/resume.pdf exists."
        )

    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    combined = "\n".join(pages).strip()
    if not combined:
        raise ValueError("Unable to extract text from resume PDF.")
    return combined
