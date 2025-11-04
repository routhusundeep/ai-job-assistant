"""SQLite helpers for the AI job assistant."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_job_id
    ON job_postings(job_id)
    WHERE job_id IS NOT NULL;
"""


def ensure_schema(database_path: Path) -> None:
    """Create the jobs table and supporting indexes if they do not exist."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        conn.executescript(DDL)
        conn.commit()


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
                url
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
                :url
            )
            """,
            job,
        )
        conn.commit()
        return cursor.rowcount > 0


def insert_job_dataclass(database_path: Path, job) -> bool:
    """Helper that accepts a dataclass instance."""
    return insert_job(database_path, asdict(job))
