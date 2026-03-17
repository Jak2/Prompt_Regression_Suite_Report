"""
Assertion Engine — orchestrates all assertion types for a single test case.

Execution order (designed for cost efficiency):
  1. Rule-based   — free, instant, fail-fast
  2. Semantic     — local, ~5ms, no API cost
  3. LLM judge    — expensive, only runs if rules + semantic pass

Aggregation: weighted mean of individual assertion scores.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..models.result import AssertionResult
from ..models.test_case import AssertionConfig, TestCase
from .judge import LLMJudgeAssertion
from .rule_based import RuleBasedAssertion, RULE_BASED_TYPES
from .semantic import SemanticSimilarityAssertion

logger = logging.getLogger(__name__)


class AssertionEngine:
    """Runs all assertions for a test case and aggregates scores."""

    def __init__(self, judge_client=None) -> None:  # type: ignore[annotation-unchecked]
        self._rule = RuleBasedAssertion()
        self._semantic = SemanticSimilarityAssertion()
        self._judge = LLMJudgeAssertion(judge_client) if judge_client else None

    async def run(
        self,
        response: str,
        test_case: TestCase,
        latency_ms: int = 0,
    ) -> tuple[float, list[AssertionResult]]:
        """
        Execute all assertions in priority order.
        Returns (overall_score, [AssertionResult]).
        """
        context = {
            "expected_behavior": test_case.expected_behavior,
            "original_prompt": "",  # populated by runner
            "latency_ms": latency_ms,
        }

        results: list[AssertionResult] = []

        # Sort: rule-based first, semantic second, judge last
        ordered = _sort_assertions(test_case.assertions)

        for cfg in ordered:
            result = await self._evaluate_one(response, cfg, context)
            results.append(result)

            # Fail-fast: skip expensive checks if a rule-based check fails hard
            if cfg.type in RULE_BASED_TYPES and not result.passed:
                logger.debug(
                    "Test '%s': failing fast after rule '%s' failed",
                    test_case.name,
                    cfg.type,
                )
                # Mark remaining as skipped rather than running them
                break

        overall = _weighted_mean(results)
        return overall, results

    async def _evaluate_one(
        self,
        response: str,
        config: AssertionConfig,
        context: dict,
    ) -> AssertionResult:
        if config.type in RULE_BASED_TYPES:
            return await self._rule.evaluate(response, config, context)
        if config.type == "semantic_similarity":
            return await self._semantic.evaluate(response, config, context)
        if config.type == "llm_judge":
            if self._judge is None:
                return AssertionResult(
                    type="llm_judge",
                    passed=False,
                    score=0.0,
                    explanation="No judge client configured",
                    weight=config.weight,
                )
            return await self._judge.evaluate(response, config, context)
        return AssertionResult(
            type=config.type,
            passed=False,
            score=0.0,
            explanation=f"Unknown assertion type: {config.type}",
            weight=config.weight,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

_TYPE_ORDER = {t: 0 for t in RULE_BASED_TYPES}
_TYPE_ORDER["semantic_similarity"] = 1
_TYPE_ORDER["llm_judge"] = 2


def _sort_assertions(configs: list[AssertionConfig]) -> list[AssertionConfig]:
    return sorted(configs, key=lambda c: _TYPE_ORDER.get(c.type, 99))


def _weighted_mean(results: list[AssertionResult]) -> float:
    if not results:
        return 0.0
    total_weight = sum(r.weight for r in results)
    if total_weight == 0:
        return 0.0
    return round(sum(r.score * r.weight for r in results) / total_weight, 4)
