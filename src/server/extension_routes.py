"""Routes supporting the Chrome extension autofill workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..sql import fetch_job_with_score
from .config import get_database_path

router = APIRouter(prefix="/extension", tags=["extension"])

PERSONAL_PATH = Path("data/personal.json")


class FieldDescriptor(BaseModel):
    name: Optional[str]
    field_id: Optional[str]
    label: Optional[str]
    placeholder: Optional[str]
    type: Optional[str]


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


def _match_value(personal: Dict[str, str], field: FieldDescriptor) -> Optional[str]:
    """Simple heuristic mapping without LLM to keep the extension thin."""
    candidates = [field.name, field.field_id, field.label, field.placeholder]
    text = " ".join(filter(None, candidates)).lower()
    if not text:
        return None

    def pick(*keys):
        for key in keys:
            if key in personal:
                return str(personal[key])
        return None

    def pick_full_name() -> Optional[str]:
        full = pick("full_name", "name")
        if full:
            return full
        first = pick("first_name", "firstname", "name")
        last = pick("last_name", "lastname")
        if first and last:
            return f"{first} {last}"
        return first or last

    if "full name" in text or "fullname" in text or ("full" in text and "name" in text):
        return pick_full_name()
    if "email" in text:
        return pick("email", "mail")
    if "phone" in text or "mobile" in text:
        return pick("phone", "mobile")
    if "first" in text and "name" in text:
        return pick("first_name", "firstname", "name")
    if "last" in text and "name" in text:
        return pick("last_name", "lastname")
    if "name" == text.strip():
        return pick_full_name()
    if "linkedin" in text:
        return pick("linkedin", "linkedin_url")
    if "github" in text:
        return pick("github", "github_url")
    if "portfolio" in text or "website" in text:
        return pick("website", "portfolio")
    if "city" in text or "location" in text:
        return pick("location", "city")
    if "country" in text:
        return pick("country")
    if "education" in text or "degree" in text:
        return pick("education", "degree")
    if "school" in text or "university" in text:
        return pick("school", "university")
    return None


@router.post("/autofill", response_model=AutofillResponse)
async def autofill(payload: AutofillRequest) -> AutofillResponse:
    if not _allowed_host(payload.url):
        return AutofillResponse(skip=True, assignments=[])

    # Optional job-level check: ensure URL is known for the job_key if provided.
    if payload.job_key:
        record = fetch_job_with_score(get_database_path(), payload.job_key)
        if not record or not record.get("url") or urlparse(record["url"]).netloc not in payload.url:
            return AutofillResponse(skip=True, assignments=[])

    personal = _load_personal()
    assignments: List[Assignment] = []
    for field in payload.fields:
        field_id = field.field_id or field.name or field.label or field.placeholder
        if not field_id:
            continue
        value = _match_value(personal, field)
        if value:
            assignments.append(Assignment(field_id=field_id, value=value))

    return AutofillResponse(skip=False, assignments=assignments)
