"""Resume-to-job ranking helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .embedding_utils import (
    build_faiss_index,
    bytes_to_embedding,
    cosine_similarity_scores,
    embed_texts,
    embedding_to_bytes,
    faiss_search,
    load_embedding_model,
    load_resume_text,
    strip_latex_markup,
)
from .llm_refiner import RankedJob, refine_scores

__all__ = [
    "build_faiss_index",
    "bytes_to_embedding",
    "cosine_similarity_scores",
    "embed_texts",
    "embedding_to_bytes",
    "faiss_search",
    "load_embedding_model",
    "load_resume_text",
    "strip_latex_markup",
    "RankedJob",
    "refine_scores",
    "ranking_cli",
]


if TYPE_CHECKING:  # pragma: no cover
    from .rank_jobs import app as ranking_cli


def __getattr__(name: str):
    if name == "ranking_cli":
        from .rank_jobs import app as ranking_cli

        return ranking_cli
    raise AttributeError(f"module 'src.ranking' has no attribute {name!r}")
