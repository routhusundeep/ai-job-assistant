"""Configuration helpers for the FastAPI server."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("JOB_ASSISTANT_DB", "data/jobs.db"))


@lru_cache(maxsize=1)
def get_database_path() -> Path:
    """Return the SQLite database path (cached)."""

    return Path(os.environ.get("JOB_ASSISTANT_DB", DEFAULT_DB_PATH))
