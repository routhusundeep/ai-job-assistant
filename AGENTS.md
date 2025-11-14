# Repository Guidelines

## 🧠 Overview
Project: AI-Powered Job Application Assistant (CS599, lead Sundeep Routhu) delivers a CLI agent pipeline that automates job-application tasks while keeping data local and auditable.

## 🎯 Project Goals
Deliver one CLI workflow to parse LinkedIn posts, measure resume fit, tailor resumes, surface recruiters, and draft outreach emails. Every artifact persists to SQLite for reuse and audit.

## 🚀 Project Stages

Stage 1 (active): Playwright-driven LinkedIn ingestion—`JobParserAgent` logs in via `login_to_linkedin`, loads filters from CLI/YAML selectors, and writes recruiter+salary-enriched postings to SQLite through the `src/sql` helpers. Stage 2 will layer resume-fit scoring and tailored resumes; Stage 3 adds recruiter discovery, outreach drafting, and reporting.

## ⚙️ Technical Architecture
Stack: Python 3.10+, Playwright (`playwright==1.48.0`), PyYAML (`PyYAML==6.0.2`), SQLite (schema + inserts in `src/sql/`), CLI entrypoints.

## 💻 Development Setup
```bash
git clone git@github.com:routhusundeep/ai-job-assistant.git
cd ai-job-assistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
Optional VS Code tips: target `venv/bin/python`, run `black` on save, organize imports, and add a `main.py` launch config.

## 🧩 Agent Specification
- `JobParserAgent`: extract LinkedIn metadata.  
- `ResumeMatchAgent`: score candidate-job fit.  
- `ResumeGeneratorAgent`: inject job keywords into resume.  
- `RecruiterFinderAgent`: surface aligned recruiters.  
- `EmailDraftAgent`: draft outreach copy.  
Model choices and temperatures live in `agents/config.yaml`.

### JobParserAgent (Stage 1)
- Entry point: `src/scrape/job_parser.py` (run with `python -m src.scrape.job_parser`).
- Uses Playwright to authenticate (via `login_to_linkedin`), apply LinkedIn filters (`--salary-band`, `--posted-time`), and paginate job listings.
- Credentials read exclusively from `secure/login.txt`; no CLI usernames/passwords.
- YAML config (`config/scraping.yaml`) supplies: base URL/start param/page size, extra query params, throttling (`rate_limits.page_delay_seconds`), and CSS selectors (`selectors.*`) for job cards, titles, company text, and company links.
- Per job the scraper captures: job id, title, company name, company URL, recruiter profile URL, salary min/max (parsed from salary widget), description, and canonical URL.
- Data persisted through `src/sql/` (`ensure_schema`, `insert_job_dataclass`) into `job_postings` with a unique index on `job_id`.
- Logging reports whether each job was inserted or already present, plus recruiter/salary summary.

### Future Agents (Stages 2-3)

### Job Assistant Pane
- Powered by FastAPI endpoints under `/agents/*` and surfaced on the job detail page.
- Supports Gemini-based fit scoring, resume tailoring (using `data/resume.pdf` as the source of truth), and outreach drafts (email + LinkedIn).
- Outputs are persisted in SQLite tables (`job_fit_analyses`, `resume_variants`, `outreach_messages`) for auditing and reuse.

## 🧪 Evaluation Metrics
Metrics: time per application ≤15 minutes, recruiter response lift +10–20%, resume cosine similarity ≥0.85, LLM output validity ≥95%, plus qualitative recruiter sentiment logged per run.

## 📈 Cost Estimation
Claude Sonnet 4.5 spend per application: parsing $0.002, match $0.010, resume $0.020, recruiter lookup $0.007, outreach $0.003 → total ≈$0.045.

## ⚠️ Challenges & Limitations
Expect LinkedIn rate limits, PyLaTeX formatting drift, and LLM variability; UX remains CLI-only with local storage.

## 🧭 Code Style Guide
Follow PEP 8 with `black` (88 cols) and `isort`; group imports (stdlib, third party, local); prefer snake_case for functions/variables, PascalCase for classes, `_` for helpers; write Google docstrings, include type hints, rely on the `logging` module, and keep inline comments terse for non-obvious logic or scraper edge cases.

## 🧱 Project Structure
Layout: `agents/` (pipeline modules), `utils/` (database, LLM client, validators), `tests/` (pytest), plus `main.py`, `requirements.txt`, `AGENTS.md`, `README.md`.
Key Stage-1 modules:
- `src/scrape/job_parser.py`: Orchestrates Playwright scraping, calls `login_to_linkedin`, and delegates DB writes to `src/sql/`.
- `src/scrape/login.py`: Provides `load_credentials` (file-based) and `login_to_linkedin` (Playwright auth).
- `src/sql/`: Owns SQLite schema DDL and job insertion helpers.
- `config/scraping.yaml`: Defines base search params, rate limits, and all scraping selectors.


## 🧭 Next Steps
Next: implement the baseline CLI pipeline, add agent-level metrics logging, run 3–5 pilot applications, and document outcomes for the CS599 deliverable.
