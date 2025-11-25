"""FastAPI routes powering the agentic pane on the job detail page."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..agents import (
    load_master_resume_text,
    run_fit_analysis,
    run_outreach_generation,
)
from ..agents.tailor import tailor_resume_agentic
from ..sql import (
    fetch_job_with_score,
    fetch_latest_fit_analysis,
    fetch_latest_outreach_message,
    fetch_latest_resume_version,
    fetch_resume_versions,
    fetch_resume_version,
    insert_fit_analysis,
    insert_outreach_message,
    insert_resume_version,
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
    version_id: str
    page_count: Optional[int]
    status: str
    pdf_url: Optional[str]
    tex_url: Optional[str]
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
    resume_versions: List[ResumeVariantResponse]
    outreach: Optional[OutreachResponse]


@router.get("/{job_key}", response_model=AgentStateResponse)
async def get_agent_state(job_key: str) -> AgentStateResponse:
    db_path = server_db_path()
    job = _load_job(job_key, db_path)
    job_key_value = job["job_key"]

    fit = fetch_latest_fit_analysis(db_path, job_key_value)
    resume_variant = fetch_latest_resume_version(db_path, job_key_value)
    resume_versions = fetch_resume_versions(db_path, job_key_value, limit=50)
    outreach = fetch_latest_outreach_message(db_path, job_key_value)

    return AgentStateResponse(
        fit_analysis=_serialize_fit(fit),
        resume_variant=_serialize_resume(resume_variant),
        resume_versions=[rv for rv in (_serialize_resume(item) for item in resume_versions) if rv],
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
    try:
        version = tailor_resume_agentic(
            job=job,
            master_tex_path=Path("data/resume.tex"),
            class_path=Path("data/rewrite.cls"),
            instructions=payload.instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = insert_resume_version(
        db_path,
        version_id=version["version_id"],
        job_key=job["job_key"],
        job_id=job.get("job_id"),
        tex_path=version["tex_path"],
        pdf_path=version["pdf_path"],
        page_count=version.get("page_count"),
        status=version.get("status", "unknown"),
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


@router.get("/{job_key}/resume/{version_id}/pdf")
async def download_tailored_resume_pdf(job_key: str, version_id: str):
    db_path = server_db_path()
    record = fetch_resume_version(db_path, version_id)
    if not record or record["job_key"] != job_key:
        raise HTTPException(status_code=404, detail="Version not found")
    pdf_path = Path(record["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found on disk")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@router.get("/{job_key}/resume/{version_id}/tex")
async def download_tailored_resume_tex(job_key: str, version_id: str):
    db_path = server_db_path()
    record = fetch_resume_version(db_path, version_id)
    if not record or record["job_key"] != job_key:
        raise HTTPException(status_code=404, detail="Version not found")
    tex_path = Path(record["tex_path"])
    if not tex_path.exists():
        raise HTTPException(status_code=404, detail="TeX not found on disk")
    return FileResponse(
        path=tex_path,
        media_type="application/x-tex",
        filename=tex_path.name,
    )


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
    pdf_path = Path(record["pdf_path"]) if record.get("pdf_path") else None
    tex_path = Path(record["tex_path"]) if record.get("tex_path") else None
    pdf_url = (
        f"/agents/{record['job_key']}/resume/{record['version_id']}/pdf"
        if pdf_path and pdf_path.exists()
        else None
    )
    tex_url = (
        f"/agents/{record['job_key']}/resume/{record['version_id']}/tex"
        if tex_path and tex_path.exists()
        else None
    )
    return ResumeVariantResponse(
        version_id=record["version_id"],
        page_count=record.get("page_count"),
        status=record.get("status") or "unknown",
        pdf_url=pdf_url,
        tex_url=tex_url,
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
