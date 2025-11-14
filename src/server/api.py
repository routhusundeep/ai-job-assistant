"""FastAPI app that exposes job postings plus a minimal Alpine.js UI."""

from __future__ import annotations

import html
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..sql import fetch_job_with_score, fetch_jobs_with_scores
from .config import get_database_path
from .schemas import (
    JobDetailResponse,
    JobListResponse,
    JobSummary,
    SortField,
    SortOrder,
)

PAGE_SIZE = 20
app = FastAPI(title="AI Job Assistant", version="0.2.0")


@app.get("/all", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    sort_by: SortField = Query(SortField.score),
    order: SortOrder = Query(SortOrder.desc),
    search: str | None = Query(None, description="Filter by score, title, or company."),
) -> JobListResponse:
    """Return paginated job summaries with score metadata."""

    jobs_raw, total = fetch_jobs_with_scores(
        get_database_path(),
        page,
        PAGE_SIZE,
        sort_by.value,
        order.value,
        search,
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


def _render_index_page() -> str:
    """Return the HTML for the landing page."""

    return """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>AI Job Assistant – Jobs</title>
  <script defer src=\"https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js\"></script>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; margin: 2rem; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { padding: 0.5rem; border-bottom: 1px solid #ddd; text-align: left; }
    th { cursor: pointer; }
    tr:hover { background-color: #fafafa; }
    .controls { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
    .search-input { flex: 1; min-width: 200px; padding: 0.4rem; }
    button { padding: 0.4rem 0.8rem; }
    .muted { color: #6b7280; font-size: 0.9rem; }
    .error { color: #b91c1c; margin-top: 0.5rem; }
  </style>
</head>
<body x-data=\"jobTable()\" x-init=\"init()\">
  <h1>Stored Jobs</h1>
  <p class=\"muted\">Search and sort the latest scraped roles. Click any title for the detail view.</p>
  <div class=\"controls\">
    <input class=\"search-input\" type=\"text\" placeholder=\"Search title, company, score\" x-model=\"search\" @keyup.enter=\"applySearch()\" />
    <button type=\"button\" @click=\"applySearch()\">Search</button>
    <button type=\"button\" @click=\"resetSearch()\">Reset</button>
  </div>
  <div class=\"error\" x-text=\"error\" x-show=\"error\"></div>
  <p class=\"muted\" x-show=\"loading\">Loading...</p>
  <table x-show=\"!loading && jobs.length\">
    <thead>
      <tr>
        <th @click=\"sort('title')\">Role</th>
        <th @click=\"sort('company')\">Company</th>
        <th>Recruiter</th>
        <th @click=\"sort('score')\">Score</th>
        <th>LLM Score</th>
      </tr>
    </thead>
    <tbody>
      <template x-for=\"job in jobs\" :key=\"job.job_key\">
        <tr>
          <td><a :href=\"`/jobs/${job.job_key}`\" x-text=\"job.title\"></a></td>
          <td>
            <template x-if=\"job.company_url\">
              <a :href=\"job.company_url\" target=\"_blank\" rel=\"noopener\" x-text=\"job.company\"></a>
            </template>
            <template x-if=\"!job.company_url\">
              <span x-text=\"job.company\"></span>
            </template>
          </td>
          <td>
            <template x-if=\"job.recruiter_url\">
              <a :href=\"job.recruiter_url\" target=\"_blank\" rel=\"noopener\">Profile</a>
            </template>
            <template x-if=\"!job.recruiter_url\">
              <span class=\"muted\">-</span>
            </template>
          </td>
          <td x-text=\"formatScore(job.score)\"></td>
          <td x-text=\"formatScore(job.llm_refined_score)\"></td>
        </tr>
      </template>
    </tbody>
  </table>
  <p class=\"muted\" x-show=\"!loading && !jobs.length\">No jobs found.</p>
  <div class=\"controls\" style=\"margin-top: 1rem;\">
    <button type=\"button\" @click=\"goTo(page - 1)\" :disabled=\"page === 1\">Prev</button>
    <span>Page <strong x-text=\"page\"></strong> / <span x-text=\"totalPages\"></span></span>
    <button type=\"button\" @click=\"goTo(page + 1)\" :disabled=\"page === totalPages\">Next</button>
  </div>
  <script>
    function jobTable() {
      return {
        jobs: [],
        page: 1,
        totalPages: 1,
        total: 0,
        sortBy: 'score',
        order: 'desc',
        search: '',
        loading: false,
        error: '',
        init() {
          this.fetchJobs();
        },
        fetchJobs() {
          this.loading = true;
          this.error = '';
          const params = new URLSearchParams({
            page: this.page,
            sort_by: this.sortBy,
            order: this.order,
          });
          if (this.search.trim()) {
            params.append('search', this.search.trim());
          }
          fetch(`/all?${params.toString()}`)
            .then((resp) => {
              if (!resp.ok) {
                throw new Error('Failed to load jobs');
              }
              return resp.json();
            })
            .then((data) => {
              this.jobs = data.jobs;
              this.total = data.total;
              this.page = data.page;
              this.totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
            })
            .catch((err) => {
              this.error = err.message;
            })
            .finally(() => {
              this.loading = false;
            });
        },
        sort(column) {
          if (this.sortBy === column) {
            this.order = this.order === 'asc' ? 'desc' : 'asc';
          } else {
            this.sortBy = column;
            this.order = column === 'score' ? 'desc' : 'asc';
          }
          this.page = 1;
          this.fetchJobs();
        },
        applySearch() {
          this.page = 1;
          this.fetchJobs();
        },
        resetSearch() {
          this.search = '';
          this.applySearch();
        },
        goTo(target) {
          if (target < 1 || target > this.totalPages) {
            return;
          }
          this.page = target;
          this.fetchJobs();
        },
        formatScore(value) {
          if (value === null || value === undefined) {
            return '-';
          }
          return Number(value).toFixed(3);
        },
      };
    }
  </script>
</body>
</html>
"""


def _render_job_detail_page(job_key: str) -> str:
    """Return the HTML for a single job detail page."""

    safe_job_key = html.escape(job_key)
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Job {safe_job_key}</title>
  <script defer src=\"https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js\"></script>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; margin: 2rem; max-width: 800px; }}
    .muted {{ color: #6b7280; font-size: 0.9rem; }}
    .panel {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin-top: 1rem; }}
    a {{ color: #2563eb; }}
    pre {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  </style>
</head>
<body x-data=\"jobDetail('{safe_job_key}')\" x-init=\"init()\">
  <a href=\"/\">&larr; Back to jobs</a>
  <div x-show=\"loading\" class=\"muted\">Loading job...</div>
  <div x-show=\"error\" class=\"muted\" style=\"color:#b91c1c;\" x-text=\"error\"></div>
  <template x-if=\"job\">
    <section>
      <h1 x-text=\"job.title\"></h1>
      <p>
        <strong x-text=\"job.company\"></strong>
        <span class=\"muted\" x-show=\"job.company_url\">&middot; <a :href=\"job.company_url\" target=\"_blank\" rel=\"noopener\">Company site</a></span>
        <span class=\"muted\" x-show=\"job.recruiter_url\">&middot; <a :href=\"job.recruiter_url\" target=\"_blank\" rel=\"noopener\">Recruiter</a></span>
      </p>
      <div class=\"panel\">
        <p><strong>Score:</strong> <span x-text=\"formatScore(job.score)\"></span></p>
        <p><strong>LLM Score:</strong> <span x-text=\"formatScore(job.llm_refined_score)\"></span></p>
        <p><strong>Salary Range:</strong> <span x-text=\"formatSalary(job.salary_min, job.salary_max)\"></span></p>
        <p><strong>Original Posting:</strong> <a :href=\"job.url\" target=\"_blank\" rel=\"noopener\">View on LinkedIn</a></p>
      </div>
      <div class=\"panel\">
        <h2>Description</h2>
        <pre x-text=\"job.description\"></pre>
      </div>
    </section>
  </template>
  <script>
    function jobDetail(jobKey) {{
      return {{
        jobKey,
        job: null,
        loading: false,
        error: '',
        init() {{
          this.fetchJob();
        }},
        fetchJob() {{
          this.loading = true;
          this.error = '';
          fetch(`/job/${{encodeURIComponent(jobKey)}}`)
            .then((resp) => {{
              if (!resp.ok) {{
                throw new Error('Unable to load job');
              }}
              return resp.json();
            }})
            .then((data) => {{
              this.job = data;
            }})
            .catch((err) => {{
              this.error = err.message;
            }})
            .finally(() => {{
              this.loading = false;
            }});
        }},
        formatScore(value) {{
          if (value === null || value === undefined) {{
            return '-';
          }}
          return Number(value).toFixed(3);
        }},
        formatSalary(min, max) {{
          const hasMin = min !== null && min !== undefined;
          const hasMax = max !== null && max !== undefined;
          if (!hasMin && !hasMax) {{
            return 'Not provided';
          }}
          if (hasMin && hasMax) {{
            return `$${{Number(min).toLocaleString()}} - $${{Number(max).toLocaleString()}}`;
          }}
          if (hasMin) {{
            return `$${{Number(min).toLocaleString()}}`;
          }}
          return `$${{Number(max).toLocaleString()}}`;
        }},
      }};
    }}
  </script>
</body>
</html>
"""
