"""FastAPI app that exposes job postings plus a minimal Alpine.js UI."""

from __future__ import annotations

import html
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from ..sql import ensure_schema, fetch_job_with_score, fetch_jobs_with_scores
from .agent_routes import router as agent_router
from .extension_routes import router as extension_router
from .config import get_database_path
from .schemas import (
    DateFilter,
    JobDetailResponse,
    JobListResponse,
    JobSummary,
    SortField,
    SortOrder,
)

PAGE_SIZE = 20
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Ensure database schema (including new agent tables) exists when server starts.
ensure_schema(get_database_path())

app = FastAPI(title="AI Job Assistant", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(agent_router)
app.include_router(extension_router)


@app.get("/all", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    sort_by: SortField = Query(SortField.score),
    order: SortOrder = Query(SortOrder.desc),
    search: str | None = Query(None, description="Filter by score, title, or company."),
    posted_within: DateFilter = Query(
        DateFilter.any, description="Restrict results by posting recency."
    ),
) -> JobListResponse:
    """Return paginated job summaries with score metadata."""

    jobs_raw, total = fetch_jobs_with_scores(
        get_database_path(),
        page,
        PAGE_SIZE,
        sort_by.value,
        order.value,
        search,
        _date_filter_days(posted_within),
    )

    summaries: List[JobSummary] = [JobSummary(**job) for job in jobs_raw]
    return JobListResponse(
        page=page,
        page_size=PAGE_SIZE,
        total=total,
        jobs=summaries,
    )


@app.get("/job/{job_key}", response_model=JobDetailResponse)
async def job_detail(job_key: str) -> JobDetailResponse:
    """Return the job posting (and scores) for the given identifier."""

    record = fetch_job_with_score(get_database_path(), job_key)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetailResponse(**record)


@app.get("/", response_class=HTMLResponse)
async def index_page() -> HTMLResponse:
    """Serve the minimal Alpine-driven job table."""

    return HTMLResponse(_render_index_page())


@app.get("/jobs/{job_key}", response_class=HTMLResponse)
async def job_page(job_key: str) -> HTMLResponse:
    """Serve the job detail scaffold."""

    return HTMLResponse(_render_job_detail_page(job_key))


@app.get("/jobs/{job_key}/tailor", response_class=HTMLResponse)
async def tailor_resume_page(job_key: str) -> HTMLResponse:
    """Serve the dedicated resume tailoring page."""

    return HTMLResponse(_render_tailor_page(job_key))


@app.get("/jobs/{job_key}/outreach", response_class=HTMLResponse)
async def outreach_page(job_key: str) -> HTMLResponse:
    """Serve the dedicated outreach page."""

    return HTMLResponse(_render_outreach_page(job_key))


@app.get("/jobs/{job_key}/apply")
async def apply_redirect(job_key: str):
    """Redirect to the job's apply URL if available."""

    record = fetch_job_with_score(get_database_path(), job_key)
    if not record or not record.get("apply_url"):
        raise HTTPException(status_code=404, detail="Apply URL not found")
    return RedirectResponse(url=record["apply_url"])


def _render_index_page() -> str:
    """Return the HTML for the landing page."""

    return _read_template("index.html")


def _render_job_detail_page(job_key: str) -> str:
    """Return the HTML for a single job detail page."""

    safe_job_key = html.escape(job_key)
    template = _read_template("job_detail.html")
    return template.replace("{{JOB_KEY}}", safe_job_key)


def _render_tailor_page(job_key: str) -> str:
    """Return the HTML for the resume tailoring page."""

    safe_job_key = html.escape(job_key)
    template = _read_template("tailor.html")
    return template.replace("{{JOB_KEY}}", safe_job_key)


def _render_outreach_page(job_key: str) -> str:
    """Return the HTML for the outreach page."""

    safe_job_key = html.escape(job_key)
    template = _read_template("outreach.html")
    return template.replace("{{JOB_KEY}}", safe_job_key)


def _read_template(name: str) -> str:
    """Load an HTML template from disk."""

    path = TEMPLATE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing template: {path}")
    return path.read_text(encoding="utf-8")


def _date_filter_days(date_filter: DateFilter) -> int | None:
    """Convert a DateFilter value to a day window."""

    mapping = {
        DateFilter.day: 1,
        DateFilter.week: 7,
        DateFilter.month: 30,
    }
    return mapping.get(date_filter, None)
