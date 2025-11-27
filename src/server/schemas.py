"""Pydantic models for the FastAPI responses."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class SortField(str, Enum):
    """Supported columns for sorting job results."""

    score = "score"
    llm_refined_score = "llm_refined_score"
    title = "title"
    company = "company"


class SortOrder(str, Enum):
    """Supported sort directions."""

    asc = "asc"
    desc = "desc"


class JobSummary(BaseModel):
    job_key: str
    job_id: Optional[str]
    title: str
    company: str
    company_url: Optional[str]
    recruiter_url: Optional[str]
    salary_min: Optional[float]
    salary_max: Optional[float]
    url: Optional[str]
    apply_url: Optional[str]
    score: Optional[float]
    llm_refined_score: Optional[float]
    preferred_resume_version_id: Optional[str]


class JobListResponse(BaseModel):
    page: int
    page_size: int
    total: int
    jobs: List[JobSummary]


class JobDetail(BaseModel):
    job_key: str
    job_id: Optional[str]
    title: str
    company: str
    company_url: Optional[str]
    recruiter_url: Optional[str]
    salary_min: Optional[float]
    salary_max: Optional[float]
    description: str
    url: str
    apply_url: Optional[str]
    score: Optional[float]
    llm_refined_score: Optional[float]
    preferred_resume_version_id: Optional[str]


class JobDetailResponse(JobDetail):
    """Alias for clarity when returning detail payloads."""

    pass
