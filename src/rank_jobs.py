"""CLI for ranking job descriptions stored in SQLite against the local resume."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
import typer

from .embedding_utils import (
    cosine_similarity_scores,
    embed_texts,
    load_embedding_model,
    load_resume_text,
)
from .llm_refiner import RankedJob, refine_scores
from .sql import ensure_schema, fetch_job_descriptions, upsert_score

LOGGER = logging.getLogger(__name__)
DEFAULT_RESUME_PATH = Path("config/resume.tex")
DEFAULT_DB_PATH = Path("data/jobs.db")
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

app = typer.Typer(help="Rank stored job descriptions against the resume.")


@dataclass(frozen=True)
class JobDescription:
    """Normalized representation of a job description pulled from SQLite."""

    job_id: str
    description: str


def _configure_logging(verbose: bool) -> None:
    """Initialize logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_jobs_from_db(db_path: Path) -> List[JobDescription]:
    """Fetch job descriptions from the job_postings table."""
    rows = fetch_job_descriptions(db_path)
    jobs = [
        JobDescription(job_id=str(job_id), description=str(description))
        for job_id, description in rows
    ]
    if not jobs:
        raise typer.BadParameter(
            f"No job descriptions found in job_postings at {db_path}. "
            "Run the scraper to ingest posts before ranking."
        )
    return jobs


def _print_top_results(
    scores: Sequence[tuple[JobDescription, float, Optional[float]]],
    limit: int = 5,
) -> None:
    """Print the top-N scores in a simple table."""
    data = [
        {
            "job_id": job.job_id,
            "score": base_score,
            "llm_refined_score": refined,
        }
        for job, base_score, refined in scores[:limit]
    ]
    if not data:
        typer.echo("No scores to display.")
        return

    frame = pd.DataFrame(data)
    display = frame.copy()
    display["score"] = display["score"].map(lambda value: f"{value:.4f}")
    display["llm_refined_score"] = display["llm_refined_score"].map(
        lambda value: "-" if value is None else f"{value:.4f}"
    )
    typer.echo(display.to_string(index=False))


def _prepare_llm_jobs(
    ranked: Sequence[tuple[JobDescription, float]], top_n: int
) -> List[RankedJob]:
    """Convert ranked jobs into structures consumable by the LLM refiner."""
    top_jobs: List[RankedJob] = []
    for job, score in ranked[:top_n]:
        top_jobs.append(
            RankedJob(job_id=job.job_id, description=job.description, score=score)
        )
    return top_jobs


@app.command()
def main(
    db_path: Path = typer.Option(DEFAULT_DB_PATH, help="Path to the SQLite database."),
    resume_path: Path = typer.Option(
        DEFAULT_RESUME_PATH, help="Path to the LaTeX resume."
    ),
    model_name: str = typer.Option(
        DEFAULT_MODEL, help="Sentence-transformer model name."
    ),
    use_llm: bool = typer.Option(
        False, help="Enable Gemini/GPT reranking if configured."
    ),
    llm_provider: Optional[str] = typer.Option(
        None, help="Override LLM provider when --use-llm is set (gemini|openai)."
    ),
    llm_model: Optional[str] = typer.Option(
        None, help="Override remote LLM model id when --use-llm is set."
    ),
    llm_top_n: int = typer.Option(5, help="Number of top jobs to send to the LLM."),
    verbose: bool = typer.Option(False, help="Enable debug logging.", is_flag=True),
):
    """Rank job descriptions against the resume and persist scores."""
    _configure_logging(verbose)

    ensure_schema(db_path)

    LOGGER.info("Loading resume from %s", resume_path)
    resume_text = load_resume_text(resume_path)
    if not resume_text:
        raise typer.BadParameter(f"Resume at {resume_path} is empty or unreadable.")

    LOGGER.info("Fetching job descriptions from %s", db_path)
    jobs = _load_jobs_from_db(db_path)

    model = load_embedding_model(model_name)
    LOGGER.info("Embedding resume and %d job descriptions", len(jobs))
    resume_embedding = embed_texts(model, [resume_text])[0]
    job_embeddings = embed_texts(model, (job.description for job in jobs))

    similarities = cosine_similarity_scores(resume_embedding, job_embeddings)
    ranked_jobs: List[tuple[JobDescription, float]] = sorted(
        zip(jobs, similarities),
        key=lambda item: item[1],
        reverse=True,
    )

    refined_scores: Dict[str, float] = {}
    if use_llm:
        LOGGER.info("LLM refinement requested; preparing top %d jobs.", llm_top_n)
        llm_candidates = _prepare_llm_jobs(ranked_jobs, max(1, llm_top_n))
        refined_scores = refine_scores(
            llm_candidates, provider=llm_provider, model_name=llm_model
        )
        LOGGER.info("LLM returned refined scores for %d jobs.", len(refined_scores))

    LOGGER.info("Persisting scores to SQLite at %s", db_path)
    for job, base_score in ranked_jobs:
        refined_score = refined_scores.get(job.job_id)
        upsert_score(db_path, job.job_id, float(base_score), refined_score)

    ranked_with_refined: List[tuple[JobDescription, float, Optional[float]]] = [
        (job, score, refined_scores.get(job.job_id)) for job, score in ranked_jobs
    ]

    _print_top_results(ranked_with_refined)

    typer.echo(f"Updated {len(ranked_jobs)} records at {datetime.now().isoformat()}.")


if __name__ == "__main__":
    app()
