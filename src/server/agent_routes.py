"""FastAPI routes powering the agentic pane on the job detail page."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents import (
    load_master_resume_text,
    run_fit_analysis,
    run_outreach_generation,
    run_resume_tailoring,
)
from ..sql import (
    fetch_job_with_score,
    fetch_latest_fit_analysis,
    fetch_latest_outreach_message,
    fetch_latest_resume_variant,
    insert_fit_analysis,
    insert_outreach_message,
    insert_resume_variant,
)
from .config import get_database_path as server_db_path

router = APIRouter(prefix="/agents", tags=["agents"])


class InstructionPayload(BaseModel):
    instructions: Optional[str] = None


class FitAnalysisResponse(BaseModel):
    summary: str
    score: Optional[float]
    created_at: Optional[str] = None
    instructions: Optional[str] = None


class ResumeVariantResponse(BaseModel):
    content: str
    created_at: Optional[str] = None
    instructions: Optional[str] = None


class OutreachResponse(BaseModel):
    email_text: str
    linkedin_text: str
    created_at: Optional[str] = None
    instructions: Optional[str] = None


class AgentStateResponse(BaseModel):
    fit_analysis: Optional[FitAnalysisResponse]
    resume_variant: Optional[ResumeVariantResponse]
    outreach: Optional[OutreachResponse]


@router.get("/{job_key}", response_model=AgentStateResponse)
async def get_agent_state(job_key: str) -> AgentStateResponse:
    db_path = server_db_path()
    job = _load_job(job_key, db_path)
    job_key_value = job["job_key"]

    fit = fetch_latest_fit_analysis(db_path, job_key_value)
    resume_variant = fetch_latest_resume_variant(db_path, job_key_value)
    outreach = fetch_latest_outreach_message(db_path, job_key_value)

    return AgentStateResponse(
        fit_analysis=_serialize_fit(fit),
        resume_variant=_serialize_resume(resume_variant),
        outreach=_serialize_outreach(outreach),
    )


@router.post("/{job_key}/fit-score", response_model=FitAnalysisResponse)
async def trigger_fit_analysis(job_key: str, payload: InstructionPayload) -> FitAnalysisResponse:
    db_path = server_db_path()
    job = _load_job(job_key, db_path)
    resume_text = load_master_resume_text()

    try:
        result = run_fit_analysis(job=job, resume_text=resume_text, instructions=payload.instructions)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = insert_fit_analysis(
        db_path,
        job_key=job["job_key"],
        job_id=job.get("job_id"),
        score=result.get("score"),
        summary=result.get("summary", ""),
        instructions=payload.instructions,
    )
    return _serialize_fit(stored)


@router.post("/{job_key}/tailor-resume", response_model=ResumeVariantResponse)
async def trigger_resume_tailoring(job_key: str, payload: InstructionPayload) -> ResumeVariantResponse:
    db_path = server_db_path()
    job = _load_job(job_key, db_path)
    resume_text = load_master_resume_text()

    try:
        result = run_resume_tailoring(
            job=job,
            resume_text=resume_text,
            instructions=payload.instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = insert_resume_variant(
        db_path,
        job_key=job["job_key"],
        job_id=job.get("job_id"),
        content=result.get("content", ""),
        instructions=payload.instructions,
    )
    return _serialize_resume(stored)


@router.post("/{job_key}/outreach", response_model=OutreachResponse)
async def trigger_outreach(job_key: str, payload: InstructionPayload) -> OutreachResponse:
    db_path = server_db_path()
    job = _load_job(job_key, db_path)
    resume_text = load_master_resume_text()

    try:
        result = run_outreach_generation(
            job=job,
            resume_text=resume_text,
            instructions=payload.instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = insert_outreach_message(
        db_path,
        job_key=job["job_key"],
        job_id=job.get("job_id"),
        email_text=result.get("email", ""),
        linkedin_text=result.get("linkedin", ""),
        instructions=payload.instructions,
    )
    return _serialize_outreach(stored)


def _load_job(job_key: str, db_path):
    job = fetch_job_with_score(db_path, job_key)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _serialize_fit(record: Optional[dict]) -> Optional[FitAnalysisResponse]:
    if not record:
        return None
    return FitAnalysisResponse(
        summary=record["summary"],
        score=record.get("score"),
        created_at=record.get("created_at"),
        instructions=record.get("instructions"),
    )


def _serialize_resume(record: Optional[dict]) -> Optional[ResumeVariantResponse]:
    if not record:
        return None
    return ResumeVariantResponse(
        content=record["content"],
        created_at=record.get("created_at"),
        instructions=record.get("instructions"),
    )


def _serialize_outreach(record: Optional[dict]) -> Optional[OutreachResponse]:
    if not record:
        return None
    return OutreachResponse(
        email_text=record["email_text"],
        linkedin_text=record["linkedin_text"],
        created_at=record.get("created_at"),
        instructions=record.get("instructions"),
    )
