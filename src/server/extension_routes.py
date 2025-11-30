"""Routes supporting the Chrome extension autofill workflow."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.gemini import generate_gemini_content
from ..sql import fetch_job_with_score
from .config import get_database_path

router = APIRouter(prefix="/extension", tags=["extension"])
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

PERSONAL_PATH = Path("data/personal.json")


class FieldDescriptor(BaseModel):
    name: Optional[str]
    id: Optional[str]
    field_id: Optional[str]
    labels: List[str] = []
    placeholder: Optional[str]
    type: Optional[str]
    options: Optional[List[str]] = None
    multiple: Optional[bool] = None
    semantic: Optional[str] = None


class AutofillRequest(BaseModel):
    url: str
    fields: List[FieldDescriptor]
    job_key: Optional[str] = None


class Assignment(BaseModel):
    field_id: str
    value: str


class AutofillResponse(BaseModel):
    skip: bool = False
    assignments: List[Assignment] = []


def _load_personal() -> Dict[str, str]:
    if not PERSONAL_PATH.exists():
        return {}
    try:
        return json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _allowed_host(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.netloc)


def _build_prompt(personal: Dict[str, str], fields: List[FieldDescriptor]) -> str:
    return (
        "You fill a job application form using ONLY the provided personal data. "
        "Return ONLY a JSON object mapping field_id to value. "
        "No code fences, no prefixes, no markdown, no text before or after. "
        "If a field cannot be filled, omit it. Do not invent new information.\n\n"
        "Personal data (JSON):\n"
        f"{json.dumps(personal, ensure_ascii=False)}\n\n"
        "Requested fields (JSON array):\n"
        f"{json.dumps([field.dict() for field in fields], ensure_ascii=False)}\n\n"
        "Respond with the JSON object only."
    )


def _run_llm_mapping(personal: Dict[str, str], fields: List[FieldDescriptor]) -> Dict[str, str]:
    prompt = _build_prompt(personal, fields)
    try:
        raw = generate_gemini_content(prompt, model="gemini-2.5-flash")
    except Exception as exc:
        logger.debug("LLM mapping failed: %s", exc)
        return {}
    raw = raw.strip()
    if not raw:
        logger.debug("LLM mapping returned empty payload")
        return {}
    # Strip fences if present
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items() if v is not None}
    except json.JSONDecodeError:
        logger.debug("LLM mapping returned non-JSON: %s", raw[:500])
        return {}
    return {}


@router.post("/autofill", response_model=AutofillResponse)
async def autofill(payload: AutofillRequest) -> AutofillResponse:
    from logging import getLogger
    logger = getLogger(__name__)
    logger.debug(
        "Autofill request: url=%s fields=%d job_key=%s fields_detail=%s",
        payload.url,
        len(payload.fields),
        payload.job_key,
        [field.dict() for field in payload.fields],
    )

    if not _allowed_host(payload.url):
        return AutofillResponse(skip=True, assignments=[])

    # Optional job-level check: ensure URL is known for the job_key if provided.
    if payload.job_key:
        record = fetch_job_with_score(get_database_path(), payload.job_key)
        if not record or not record.get("url") or urlparse(record["url"]).netloc not in payload.url:
            return AutofillResponse(skip=True, assignments=[])

    personal = _load_personal()
    if not personal:
        return AutofillResponse(skip=True, assignments=[])

    values = _run_llm_mapping(personal, payload.fields)
    logger.debug("Autofill response assignments: %s", values)
    assignments: List[Assignment] = [
        Assignment(field_id=field_id, value=value) for field_id, value in values.items() if value
    ]
    return AutofillResponse(skip=False, assignments=assignments)
