# Repository Guidelines

## 🧠 Overview
Project: AI-Powered Job Application Assistant (CS599, lead Sundeep Routhu) delivers a CLI agent pipeline that automates job-application tasks while keeping data local and auditable.

## 🎯 Project Goals
Deliver one CLI workflow to parse LinkedIn posts, measure resume fit, tailor resumes, surface recruiters, and draft outreach emails. Every artifact persists to SQLite for reuse and audit.

## 🚀 Project Stages
Stage 1 (active): LinkedIn ingestion—`JobParserAgent` captures postings with Playwright or API wrappers and stores descriptions plus metadata in SQLite. Stage 2 will layer resume-fit scoring and tailored resumes; Stage 3 adds recruiter discovery, outreach drafting, and reporting.

## ⚙️ Technical Architecture
Stack: Python 3.10+, Playwright + `linkedin-api`/`linkedin-scraper`, `google-generativeai`, SQLite, PyLaTeX, `click`, `pydantic`, `requests`, `tenacity`.

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

## 🧭 Next Steps
Next: implement the baseline CLI pipeline, add agent-level metrics logging, run 3–5 pilot applications, and document outcomes for the CS599 deliverable.
