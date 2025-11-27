"""SQLite helpers for the AI job assistant."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Mapping

DDL = """
CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    company_url TEXT,
    recruiter_url TEXT,
    salary_min REAL,
    salary_max REAL,
    description TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    apply_url TEXT,
    preferred_resume_version_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_job_id
    ON job_postings(job_id)
    WHERE job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS scores (
    job_id TEXT PRIMARY KEY,
    score REAL,
    llm_refined_score REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_embeddings (
    job_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding BLOB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, model_name)
);

CREATE TABLE IF NOT EXISTS resume_embeddings (
    resume_path TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding BLOB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resume_path, model_name)
);

CREATE TABLE IF NOT EXISTS job_fit_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL,
    job_id TEXT,
    score REAL,
    summary TEXT NOT NULL,
    instructions TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL,
    job_id TEXT,
    email_text TEXT NOT NULL,
    linkedin_text TEXT NOT NULL,
    instructions TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_versions (
    version_id TEXT PRIMARY KEY,
    job_key TEXT NOT NULL,
    job_id TEXT,
    tex_path TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    page_count INTEGER,
    status TEXT NOT NULL,
    instructions TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_schema(database_path: Path) -> None:
    """Create the jobs table and supporting indexes if they do not exist."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        conn.executescript(DDL)
        _add_column_if_missing(conn, "job_postings", "apply_url", "TEXT")
        _add_column_if_missing(conn, "job_postings", "preferred_resume_version_id", "TEXT")
        conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it does not already exist."""
    existing = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if any(row[1] == column for row in existing):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def insert_job(database_path: Path, job: Mapping[str, Any]) -> bool:
    """Insert a job posting. Returns True if inserted, False if existed."""
    with sqlite3.connect(database_path) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO job_postings (
                job_id,
                title,
                company,
                company_url,
                recruiter_url,
                salary_min,
                salary_max,
                description,
                url,
                apply_url
            )
            VALUES (
                :job_id,
                :title,
                :company,
                :company_url,
                :recruiter_url,
                :salary_min,
                :salary_max,
                :description,
                :url,
                :apply_url
            )
            """,
            job,
        )
        conn.commit()
        return cursor.rowcount > 0


def insert_job_dataclass(database_path: Path, job) -> bool:
    """Helper that accepts a dataclass instance."""
    return insert_job(database_path, asdict(job))


def upsert_score(
    database_path: Path, job_id: str, score: float, llm_refined_score: float | None
) -> None:
    """Insert or update a job similarity score."""
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO scores (job_id, score, llm_refined_score)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                score=excluded.score,
                llm_refined_score=COALESCE(
                    excluded.llm_refined_score,
                    llm_refined_score
                ),
                updated_at=CURRENT_TIMESTAMP
            """,
            (job_id, score, llm_refined_score),
        )
        conn.commit()


def fetch_job_descriptions(database_path: Path) -> List[Tuple[str, str]]:
    """Return (job_id, description) rows from job_postings."""
    with sqlite3.connect(database_path) as conn:
        rows = conn.execute(
            """
            SELECT job_id, description
            FROM job_postings
            WHERE description IS NOT NULL
            AND TRIM(description) != ''
            """
        ).fetchall()

    return [(row[0], row[1]) for row in rows if row[0]]


def fetch_job_embeddings(
    database_path: Path, job_ids: Iterable[str], model_name: str
) -> Dict[str, bytes]:
    """Return embeddings for the given job ids keyed by job_id."""
    job_ids = list(job_ids)
    if not job_ids:
        return {}

    placeholders = ",".join("?" for _ in job_ids)
    params: Tuple[Any, ...] = (model_name, *job_ids)

    with sqlite3.connect(database_path) as conn:
        rows = conn.execute(
            f"""
            SELECT job_id, embedding
            FROM job_embeddings
            WHERE model_name = ?
              AND job_id IN ({placeholders})
            """,
            params,
        ).fetchall()

    return {row[0]: row[1] for row in rows}


def upsert_job_embedding(
    database_path: Path, job_id: str, model_name: str, embedding: bytes
) -> None:
    """Store a job embedding for the given model."""
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO job_embeddings (job_id, model_name, embedding)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id, model_name) DO UPDATE SET
                embedding=excluded.embedding,
                updated_at=CURRENT_TIMESTAMP
            """,
            (job_id, model_name, sqlite3.Binary(embedding)),
        )
        conn.commit()


def fetch_resume_embedding(
    database_path: Path, resume_path: Path, model_name: str
) -> Optional[bytes]:
    """Retrieve the stored embedding for the resume if present."""
    with sqlite3.connect(database_path) as conn:
        row = conn.execute(
            """
            SELECT embedding
            FROM resume_embeddings
            WHERE resume_path = ?
              AND model_name = ?
            """,
            (str(resume_path), model_name),
        ).fetchone()
    return row[0] if row else None


def upsert_resume_embedding(
    database_path: Path, resume_path: Path, model_name: str, embedding: bytes
) -> None:
    """Persist the resume embedding for reuse."""
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO resume_embeddings (resume_path, model_name, embedding)
            VALUES (?, ?, ?)
            ON CONFLICT(resume_path, model_name) DO UPDATE SET
                embedding=excluded.embedding,
                updated_at=CURRENT_TIMESTAMP
            """,
            (str(resume_path), model_name, sqlite3.Binary(embedding)),
        )
        conn.commit()


def fetch_jobs_with_scores(
    database_path: Path,
    page: int,
    page_size: int,
    sort_by: str,
    order: str,
    search: Optional[str],
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated job postings joined with similarity scores."""

    sort_column_map = {
        "score": "s.score",
        "llm_refined_score": "s.llm_refined_score",
        "title": "jp.title",
        "company": "jp.company",
    }
    sort_column = sort_column_map.get(sort_by, "s.score")
    sort_direction = "DESC" if order.lower() == "desc" else "ASC"

    where_clauses: List[str] = []
    params: List[Any] = []

    if search:
        trimmed = search.strip()
        if trimmed:
            pattern = f"%{trimmed}%"
            where_clauses.append(
                "(jp.title LIKE ? OR jp.company LIKE ? OR CAST(s.score AS TEXT) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    offset = (page - 1) * page_size

    base_query = """
        FROM job_postings AS jp
        LEFT JOIN scores AS s ON s.job_id = jp.job_id
    """

    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        count_row = conn.execute(
            f"SELECT COUNT(*) {base_query} {where_sql}", params
        ).fetchone()
        total_count = int(count_row[0]) if count_row else 0

        rows = conn.execute(
            f"""
            SELECT
                jp.id,
                jp.job_id,
                jp.title,
                jp.company,
                jp.company_url,
                jp.recruiter_url,
                jp.salary_min,
                jp.salary_max,
                jp.url,
                jp.apply_url,
                jp.preferred_resume_version_id,
                s.score,
                s.llm_refined_score,
                s.updated_at AS score_updated_at
            {base_query}
            {where_sql}
            ORDER BY {sort_column} {sort_direction}, jp.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

    jobs: List[Dict[str, Any]] = []
    for row in rows:
        job_id_value = row["job_id"] if row["job_id"] else str(row["id"])
        jobs.append(
            {
                "job_key": job_id_value,
                "job_id": row["job_id"],
                "title": row["title"],
                "company": row["company"],
                "company_url": row["company_url"],
                "recruiter_url": row["recruiter_url"],
                "salary_min": row["salary_min"],
                "salary_max": row["salary_max"],
                "url": row["url"],
                "apply_url": row["apply_url"],
                "preferred_resume_version_id": row["preferred_resume_version_id"],
                "score": row["score"],
                "llm_refined_score": row["llm_refined_score"],
            }
        )

    return jobs, total_count


def fetch_job_with_score(database_path: Path, job_key: str) -> Optional[Dict[str, Any]]:
    """Return a single job posting (joined with score) by job_id or numeric id."""

    params: List[Any] = [job_key]
    where_clause = "jp.job_id = ?"

    query = """
        SELECT
            jp.id,
            jp.job_id,
            jp.title,
            jp.company,
            jp.company_url,
            jp.recruiter_url,
            jp.salary_min,
            jp.salary_max,
            jp.description,
            jp.url,
            jp.apply_url,
            jp.preferred_resume_version_id,
            jp.created_at,
            s.score,
            s.llm_refined_score,
            s.updated_at AS score_updated_at
        FROM job_postings AS jp
        LEFT JOIN scores AS s ON s.job_id = jp.job_id
        WHERE {where_clause}
        LIMIT 1
    """

    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(query.format(where_clause=where_clause), params).fetchone()

        if not row and job_key.isdigit():
            row = conn.execute(
                query.format(where_clause="jp.id = ?"), (int(job_key),)
            ).fetchone()

    if not row:
        return None

    job_key_value = row["job_id"] if row["job_id"] else str(row["id"])
    return {
        "job_key": job_key_value,
        "job_id": row["job_id"],
        "title": row["title"],
        "company": row["company"],
        "company_url": row["company_url"],
        "recruiter_url": row["recruiter_url"],
        "salary_min": row["salary_min"],
        "salary_max": row["salary_max"],
        "description": row["description"],
        "url": row["url"],
        "apply_url": row["apply_url"],
        "preferred_resume_version_id": row["preferred_resume_version_id"],
        "score": row["score"],
        "llm_refined_score": row["llm_refined_score"],
    }


def set_preferred_resume_version(
    database_path: Path, job_key: str, version_id: Optional[str]
) -> None:
    """Set the preferred resume version for a job (job_id or numeric id)."""
    with sqlite3.connect(database_path) as conn:
        # Resolve job_key to job_id if needed
        params = [version_id, job_key]
        where_clause = "job_id = ?"
        if not job_key or job_key.isdigit():
            # Attempt numeric id fallback
            params = [version_id, job_key if job_key else None]
            where_clause = "id = ?"

        # Try job_id first
        conn.execute(
            f"""
            UPDATE job_postings
            SET preferred_resume_version_id = ?
            WHERE {where_clause}
            """,
            params,
        )
        conn.commit()


def insert_fit_analysis(
    database_path: Path,
    *,
    job_key: str,
    job_id: Optional[str],
    score: Optional[float],
    summary: str,
    instructions: Optional[str],
) -> Dict[str, Any]:
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO job_fit_analyses (job_key, job_id, score, summary, instructions)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_key, job_id, score, summary, instructions),
        )
        conn.commit()

    return fetch_latest_fit_analysis(database_path, job_key) or {}


def fetch_latest_fit_analysis(
    database_path: Path, job_key: str
) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, job_key, job_id, score, summary, instructions, created_at
            FROM job_fit_analyses
            WHERE job_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_key,),
        ).fetchone()

    if not row:
        return None
    return dict(row)


def insert_outreach_message(
    database_path: Path,
    *,
    job_key: str,
    job_id: Optional[str],
    email_text: str,
    linkedin_text: str,
    instructions: Optional[str],
) -> Dict[str, Any]:
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO outreach_messages (job_key, job_id, email_text, linkedin_text, instructions)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_key, job_id, email_text, linkedin_text, instructions),
        )
        conn.commit()

    return fetch_latest_outreach_message(database_path, job_key) or {}


def fetch_latest_outreach_message(
    database_path: Path, job_key: str
) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, job_key, job_id, email_text, linkedin_text, instructions, created_at
            FROM outreach_messages
            WHERE job_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_key,),
        ).fetchone()

    if not row:
        return None
    return dict(row)


def insert_resume_version(
    database_path: Path,
    *,
    version_id: str,
    job_key: str,
    job_id: Optional[str],
    tex_path: Path,
    pdf_path: Path,
    page_count: Optional[int],
    status: str,
    instructions: Optional[str],
) -> Dict[str, Any]:
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO resume_versions (
                version_id,
                job_key,
                job_id,
                tex_path,
                pdf_path,
                page_count,
                status,
                instructions
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                job_key,
                job_id,
                str(tex_path),
                str(pdf_path),
                page_count,
                status,
                instructions,
            ),
        )
        conn.commit()

    return fetch_resume_version(database_path, version_id) or {}


def fetch_latest_resume_version(
    database_path: Path, job_key: str
) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT version_id, job_key, job_id, tex_path, pdf_path, page_count, status, instructions, created_at
            FROM resume_versions
            WHERE job_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_key,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def fetch_resume_version(
    database_path: Path, version_id: str
) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT version_id, job_key, job_id, tex_path, pdf_path, page_count, status, instructions, created_at
            FROM resume_versions
            WHERE version_id = ?
            LIMIT 1
            """,
            (version_id,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def fetch_resume_versions(
    database_path: Path, job_key: str, limit: int = 20
) -> List[Dict[str, Any]]:
    """Return recent resume versions for a job, newest first."""
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT version_id, job_key, job_id, tex_path, pdf_path, page_count, status, instructions, created_at
            FROM resume_versions
            WHERE job_key = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (job_key, limit),
        ).fetchall()
    return [dict(row) for row in rows]
