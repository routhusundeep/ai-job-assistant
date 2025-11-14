"""Utilities for loading embeddings and preparing text for similarity scoring."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import faiss
import numpy as np
from pylatexenc.latex2text import LatexNodes2Text
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

LOGGER = logging.getLogger(__name__)
LATEX_TEXT_CONVERTER = LatexNodes2Text()


def strip_latex_markup(text: str) -> str:
    """Convert LaTeX markup into plain text using pylatexenc."""
    try:
        converted = LATEX_TEXT_CONVERTER.latex_to_text(text)
    except Exception as exc:  # pragma: no cover - pylatexenc failures are rare
        LOGGER.error("Failed to parse LaTeX resume: %s", exc)
        converted = text
    condensed = re.sub(r"\s+", " ", converted)
    return condensed.strip()


def load_resume_text(resume_path: Path) -> str:
    """Load and clean the resume file."""
    raw_text = resume_path.read_text(encoding="utf-8")
    cleaned = strip_latex_markup(raw_text)
    if not cleaned:
        LOGGER.warning("Resume text appears empty after stripping LaTeX markup.")
    return cleaned


@lru_cache(maxsize=2)
def load_embedding_model(model_name: str) -> SentenceTransformer:
    """Load a sentence-transformer model, caching instances by name."""
    LOGGER.info("Loading sentence-transformer model: %s", model_name)
    return SentenceTransformer(model_name)


def _should_use_e5_formatting(model_name: str) -> bool:
    return "e5" in model_name.lower()


def _format_for_e5(texts: Iterable[str], is_query: bool) -> list[str]:
    prefix = "query: " if is_query else "passage: "
    return [f"{prefix}{text.strip()}" for text in texts]


def embed_texts(
    model: SentenceTransformer,
    texts: Iterable[str],
    *,
    model_name: str,
    is_query: bool = False,
) -> np.ndarray:
    """Embed one or more texts with the provided model."""
    prepared_texts = list(texts)
    if _should_use_e5_formatting(model_name):
        prepared_texts = _format_for_e5(prepared_texts, is_query=is_query)

    embeddings = model.encode(
        prepared_texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(embeddings, dtype=np.float32)


def cosine_similarity_scores(
    query_embedding: np.ndarray, document_embeddings: np.ndarray
) -> np.ndarray:
    """Compute cosine similarity between a single query vector and a matrix of document vectors."""
    query = np.atleast_2d(query_embedding)
    similarities = cosine_similarity(query, document_embeddings)
    return similarities[0]


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialize an embedding to bytes."""
    return np.asarray(embedding, dtype=np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialize bytes into a float32 embedding."""
    return np.frombuffer(data, dtype=np.float32).copy()


def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    """Create a FAISS index from normalized embeddings."""
    if embeddings.dtype != np.float32:
        embeddings = embeddings.astype(np.float32)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return index


def faiss_search(
    index: faiss.IndexFlatIP, query_embedding: np.ndarray, k: int
) -> tuple[np.ndarray, np.ndarray]:
    """Run a FAISS search for the provided query embedding."""
    if query_embedding.dtype != np.float32:
        query_embedding = query_embedding.astype(np.float32)
    distances, indices = index.search(
        np.asarray([query_embedding], dtype=np.float32), k
    )
    return distances[0], indices[0]
