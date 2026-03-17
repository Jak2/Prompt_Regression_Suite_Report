"""
Semantic similarity assertion using sentence-transformers.

Model: all-MiniLM-L6-v2
  - 80 MB on disk, ~22 MB in RAM
  - 384-dimensional embeddings
  - Runs locally — zero API cost
  - Trained to maximise cosine similarity between semantically equivalent sentences

Design: The model is loaded lazily and cached as a module-level singleton.
Loading happens once per process (~0.5s). Subsequent calls are fast (~5ms per pair).

Why cosine similarity over other distances?
  - Scale-invariant: longer responses don't automatically score lower
  - Maps cleanly to [0, 1] after normalisation
  - Standard practice in sentence-embedding literature
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import numpy as np

from ..models.result import AssertionResult
from ..models.test_case import AssertionConfig
from .base import Assertion

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _get_model():
    """Load sentence-transformer model once; cache for the process lifetime."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        logger.info("Loading sentence-transformer model '%s'…", _MODEL_NAME)
        return SentenceTransformer(_MODEL_NAME)
    except ImportError:
        logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors, returned in [0, 1]."""
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    raw = float(np.dot(a, b) / denom)
    # Clip to [0, 1] — negative values mean orthogonal/opposite, treat as 0
    return max(0.0, min(1.0, raw))


class SemanticSimilarityAssertion(Assertion):
    """Embeds response + reference into vector space; scores via cosine similarity."""

    async def evaluate(
        self,
        response: str,
        config: AssertionConfig,
        context: dict,
    ) -> AssertionResult:
        model = _get_model()
        if model is None:
            return AssertionResult(
                type="semantic_similarity",
                passed=False,
                score=0.0,
                explanation="sentence-transformers not available",
                weight=config.weight,
            )

        reference = config.reference_answer or context.get("expected_behavior", "")
        if not reference:
            return AssertionResult(
                type="semantic_similarity",
                passed=False,
                score=0.0,
                explanation="No reference answer provided for semantic similarity check",
                weight=config.weight,
            )

        embeddings = model.encode([response, reference], convert_to_numpy=True)
        score = _cosine_similarity(embeddings[0], embeddings[1])
        passed = score >= config.threshold

        return AssertionResult(
            type="semantic_similarity",
            passed=passed,
            score=round(score, 4),
            explanation=(
                f"Cosine similarity {score:.3f} "
                f"({'≥' if passed else '<'} threshold {config.threshold})"
            ),
            weight=config.weight,
        )
