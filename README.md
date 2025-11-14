# ai-job-assistant

AI-powered assistant that ingests LinkedIn postings, scores them against your resume, and now exposes the results through a lightweight FastAPI + Alpine.js dashboard.

## Running the FastAPI server

```bash
uvicorn src.server.api:app --reload
```

The server defaults to `data/jobs.db`. Override by exporting `JOB_ASSISTANT_DB=/path/to/jobs.db` before starting Uvicorn.

## REST endpoints

- `GET /all` – Paginated list (20 per page) of job postings with company links, recruiter links, similarity scores, and LLM-refined scores. Supports `page`, `sort_by` (`score`, `llm_refined_score`, `title`, `company`), `order` (`asc|desc`), and `search` (matches title/company/score).
- `GET /job/{job_key}` – Full detail for a single job, including salary band, description, and outbound URLs. Accepts either the LinkedIn `job_id` or the internal numeric id.

## Web UI

- `GET /` – Jobs table powered by Alpine.js. Click headers to sort, filter with the search box, and jump to recruiter/company pages.
- `GET /jobs/{job_key}` – Detail view scaffold that surfaces all metadata and will host future Stage 2/3 tooling.

Both pages call the REST API directly, so no additional frontend build tooling is required.
