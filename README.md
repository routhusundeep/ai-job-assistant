# AI Job Assistant

## Introduction
AI Job Assistant is a local-first workflow that ingests LinkedIn postings, ranks them against your resume, tailors resumes and outreach copy with Gemini, and optionally autofills job portals through a Chrome extension. Every stage logs outputs to SQLite so you can audit decisions, rerun analyses, or plug additional agents into the same database.

## System Description
- **Scraping** – Playwright-based CLI logs in with stored LinkedIn credentials, applies selectors from `config/scraping.yaml`, and persists recruiter- and salary-enriched job cards to SQLite.
- **Ranking** – A CLI embeds each job description and the canonical resume, caches vectors, and uses FAISS to surface the highest-fit roles; optional Gemini reranking produces narrative scores.
- **Agents** – FastAPI endpoints expose fit analysis, resume tailoring (iterative LaTeX rewrites), and outreach generation. Outputs are versioned so you can review PDFs, TeX, and instructions per job.
- **Dashboard & API** – A lightweight Alpine.js UI plus REST endpoints (`/all`, `/job/{key}`, `/agents/*`) make it easy to browse jobs and trigger agents.
- **Autofill Extension** – A Manifest V3 Chrome extension inspects form fields, requests assignments from the local API, and injects tailored resume data and outreach drafts into application portals.

## Data & Secrets Required
- **LinkedIn credentials** – Place username/password on separate lines in `secure/login.txt`. Session cookies are cached in `secure/session.json`.
- **Resume sources** – Maintain the master LaTeX file (default `data/resume.tex` + `data/rewrite.cls`) and render to `data/resume.pdf`. Tailoring relies on both the TeX source and compiled PDF.
- **LLM access** – Set `GOOGLE_API_KEY` in your environment so Gemini calls (resume tailoring, fit analysis, outreach) can run. All calls are issued server-side; redact sensitive resume sections if necessary.
- **Database location** – Default SQLite file is `data/jobs.db`. Override via `JOB_ASSISTANT_DB=/path/to.db` when running CLIs or the FastAPI server.
- **Chrome extension API base** – The extension defaults to `http://localhost:8000` but you can override by setting `apiBase` in Chrome storage (Options page) if the FastAPI service runs elsewhere.

## Usage
1. **Environment setup**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   export GOOGLE_API_KEY=<your_gemini_key>
   ```

2. **Scrape LinkedIn**
   ```bash
   python -m src.scrape.job_parser \
     --job-title "machine learning engineer" \
     --max-jobs 200 \
     --salary-band 5 \
     --posted-time PAST_WEEK \
     --wait-timeout 25
   ```
   The CLI reads `secure/login.txt`, uses selectors from `config/scraping.yaml`, and writes to the configured SQLite database.

3. **Rank jobs against your resume**
   ```bash
   python -m src.ranking.rank_jobs \
     --resume-path data/resume.tex \
     --db-path data/jobs.db \
     --model-name intfloat/e5-base-v2 \
     --use-llm
   ```
   Results persist to the `scores` table and are visible in the dashboard.

4. **Run the FastAPI server & dashboard**
   ```bash
   uvicorn src.server.api:app --reload
   ```
   Visit `http://localhost:8000/` for the job table or `/jobs/{job_key}` for job detail + agent pane. Agent routes live under `/agents/*`.

5. **Trigger Gemini agents**
   - Ensure `data/resume.pdf` exists (render via `python -m src.tools.render_resume`).
   - Open a job detail page and run fit analysis, resume tailoring, or outreach directly in the UI, or call the REST routes (`/agents/{job_key}/tailor-resume`, `/agents/{job_key}/outreach`).

6. **Use the Chrome autofill extension**
   ```bash
   cd extension
   npm install
   npm run build
   ```
   Load `extension/dist` as an unpacked extension in Chrome. Click the icon on a job portal to detect fields and autofill using the latest tailored resume/outreach drafts.

## Additional Notes
- All artifacts (job postings, scores, resume versions, outreach drafts) live in SQLite, making it easy to audit or export.
- Scraping and LLM usage occur locally; review logs and redact sensitive information before invoking agents if privacy is a concern.
- The pipeline is modular—swap embedding models, tweak YAML selectors, or plug new agents into the same database without rewriting the UI.

For more details, see the inline docstrings in `src/` and the Chrome extension source under `extension/src`.
