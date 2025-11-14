"""CLI for ranking job descriptions stored in SQLite against the local resume."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import typer

from .embedding_utils import (
    build_faiss_index,
    bytes_to_embedding,
    embed_texts,
    embedding_to_bytes,
    faiss_search,
    load_embedding_model,
    load_resume_text,
)
from .llm_refiner import RankedJob, refine_scores
from ..sql import (
    ensure_schema,
    fetch_job_descriptions,
    fetch_job_embeddings,
    fetch_resume_embedding,
    upsert_job_embedding,
    upsert_resume_embedding,
    upsert_score,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_RESUME_PATH = Path("config/resume.tex")
DEFAULT_DB_PATH = Path("data/jobs.db")
DEFAULT_MODEL = "intfloat/e5-base-v2"

app = typer.Typer(help="Rank stored job descriptions against the resume.")


@dataclass(frozen=True)
class JobDescription:
    """Normalized representation of a job description pulled from SQLite."""

    job_id: str
    description: str


def _configure_logging(log_level: Optional[str]) -> None:
    """Initialize logging."""
    level = logging.INFO
    if log_level:
        parsed_level = getattr(logging, log_level.upper(), None)
        if not isinstance(parsed_level, int):
            raise typer.BadParameter(f"Invalid log level: {log_level}")
        level = parsed_level
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


def _load_job_embeddings(
    db_path: Path,
    model,
    model_name: str,
    jobs: Sequence[JobDescription],
) -> np.ndarray:
    """Retrieve or compute embeddings for all jobs."""
    job_ids = [job.job_id for job in jobs]
    cached = fetch_job_embeddings(db_path, job_ids, model_name)

    embedding_map: Dict[str, np.ndarray] = {}
    missing_jobs: List[JobDescription] = []
    missing_texts: List[str] = []

    for job in jobs:
        blob = cached.get(job.job_id)
        if blob:
            embedding_map[job.job_id] = bytes_to_embedding(blob)
        else:
            missing_jobs.append(job)
            missing_texts.append(job.description)

    if missing_jobs:
        LOGGER.info("Embedding %d new job descriptions.", len(missing_jobs))
        new_embeddings = embed_texts(
            model,
            missing_texts,
            model_name=model_name,
            is_query=False,
        )
        for job, embedding in zip(missing_jobs, new_embeddings):
            embedding_map[job.job_id] = embedding
            upsert_job_embedding(
                db_path, job.job_id, model_name, embedding_to_bytes(embedding)
            )

    try:
        matrix = np.vstack([embedding_map[job.job_id] for job in jobs])
    except KeyError as exc:
        missing = exc.args[0]
        raise RuntimeError(f"Missing embedding for job_id {missing}") from exc

    return np.asarray(matrix, dtype=np.float32)


def _load_resume_embedding(
    db_path: Path,
    model,
    model_name: str,
    resume_path: Path,
    resume_text: str,
) -> np.ndarray:
    """Retrieve or compute the resume embedding."""
    cached = fetch_resume_embedding(db_path, resume_path, model_name)
    if cached:
        return bytes_to_embedding(cached)

    LOGGER.info("Embedding resume with model %s", model_name)
    embedding = embed_texts(
        model,
        [resume_text],
        model_name=model_name,
        is_query=True,
    )[0]
    upsert_resume_embedding(
        db_path, resume_path, model_name, embedding_to_bytes(embedding)
    )
    return embedding


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
        False,
        help="Enable LLM reranking (prefers local Ollama, falls back to Gemini/OpenAI).",
    ),
    llm_provider: Optional[str] = typer.Option(
        None,
        help="Override LLM provider when --use-llm is set (ollama|gemini|openai).",
    ),
    llm_model: Optional[str] = typer.Option(
        None, help="Override remote LLM model id when --use-llm is set."
    ),
    llm_top_n: int = typer.Option(5, help="Number of top jobs to send to the LLM."),
    log_level: Optional[str] = typer.Option(
        None,
        "--log-level",
        help="Explicit logging level (e.g. INFO, DEBUG, WARNING).",
    ),
):
    """Rank job descriptions against the resume and persist scores."""
    _configure_logging(log_level)

    ensure_schema(db_path)

    LOGGER.info("Loading resume from %s", resume_path)
    resume_text = load_resume_text(resume_path)
    if not resume_text:
        raise typer.BadParameter(f"Resume at {resume_path} is empty or unreadable.")

    LOGGER.info("Fetching job descriptions from %s", db_path)
    jobs = _load_jobs_from_db(db_path)

    model = load_embedding_model(model_name)
    LOGGER.info("Preparing embeddings with model %s", model_name)
    resume_embedding = _load_resume_embedding(
        db_path, model, model_name, resume_path, resume_text
    )
    job_embeddings = _load_job_embeddings(db_path, model, model_name, jobs)

    faiss_index = build_faiss_index(job_embeddings)
    search_k = len(jobs)
    _, faiss_indices = faiss_search(faiss_index, resume_embedding, search_k)
    base_scores = job_embeddings @ np.asarray(resume_embedding, dtype=np.float32)
    base_scores_map: Dict[str, float] = {
        job.job_id: float(score) for job, score in zip(jobs, base_scores)
    }

    ranked_jobs: List[tuple[JobDescription, float]] = []
    for rank_idx, job_index in enumerate(faiss_indices):
        if job_index < 0 or job_index >= len(jobs):
            continue
        job = jobs[job_index]
        ranked_jobs.append((job, base_scores_map[job.job_id]))

    refined_scores: Dict[str, float] = {}
    if use_llm:
        LOGGER.info("LLM refinement requested; preparing top %d jobs.", llm_top_n)
        llm_candidates = _prepare_llm_jobs(ranked_jobs, max(1, llm_top_n))
        refined_scores = refine_scores(
            llm_candidates,
            resume_text,
            provider=llm_provider,
            model_name=llm_model,
        )
        LOGGER.info("LLM returned refined scores for %d jobs.", len(refined_scores))

    LOGGER.info("Persisting scores to SQLite at %s", db_path)
    for job in jobs:
        base_score = base_scores_map[job.job_id]
        refined_score = refined_scores.get(job.job_id)
        upsert_score(db_path, job.job_id, float(base_score), refined_score)

    ranked_with_refined: List[tuple[JobDescription, float, Optional[float]]] = [
        (
            job,
            base_scores_map[job.job_id],
            refined_scores.get(job.job_id),
        )
        for job, _ in ranked_jobs
    ]

    _print_top_results(ranked_with_refined)

    typer.echo(f"Updated {len(ranked_jobs)} records at {datetime.now().isoformat()}.")


if __name__ == "__main__":
    app()
