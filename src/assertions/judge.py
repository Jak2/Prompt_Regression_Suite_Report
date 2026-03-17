"""
LLM-as-Judge assertion.

The judge model MUST differ from the model under test to avoid self-scoring bias.
Default: Claude → OpenAI judge; OpenAI → Anthropic judge.

The judge returns structured JSON with four scoring dimensions:
  instruction_following (0.40 weight)
  factual_accuracy      (0.30 weight)
  format_compliance     (0.20 weight)
  tone_appropriateness  (0.10 weight)

The judge prompt enforces JSON-only output because free-text responses before JSON
are a common silent failure mode that breaks parsers at scale.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..models.result import AssertionResult
from ..models.test_case import AssertionConfig
from .base import Assertion

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
You are a rigorous automated evaluator for an LLM prompt regression test suite.
Your role is to assess whether an AI-generated response meets a defined expected behaviour.
You are a neutral evaluator — you are not the model that generated the response.
You must return ONLY valid JSON. No preamble. No explanation outside the JSON.
Do not wrap the JSON in markdown code fences. Begin your response with the opening brace {"""

_JUDGE_USER_TEMPLATE = """\
EXPECTED BEHAVIOUR:
{expected_behavior}

ORIGINAL PROMPT SENT TO THE AI:
{original_prompt}

ACTUAL AI RESPONSE:
{actual_response}
{context_section}
TASK:
Evaluate whether the ACTUAL AI RESPONSE satisfies the EXPECTED BEHAVIOUR.
Score on four dimensions, then produce an overall weighted verdict.

DIMENSIONS:
- instruction_following (0.0–1.0): Did the response follow all explicit instructions?
- factual_accuracy (0.0–1.0): Are all factual claims correct and consistent with context?
- format_compliance (0.0–1.0): Does the response match any specified format requirements?
- tone_appropriateness (0.0–1.0): Is the tone and register appropriate for the context?

WEIGHTS: instruction_following=0.40, factual_accuracy=0.30, format_compliance=0.20, tone_appropriateness=0.10

REQUIRED JSON OUTPUT FORMAT:
{{
  "instruction_following": <float 0.0–1.0>,
  "factual_accuracy": <float 0.0–1.0>,
  "format_compliance": <float 0.0–1.0>,
  "tone_appropriateness": <float 0.0–1.0>,
  "overall": <float 0.0–1.0, weighted mean>,
  "passed": <true if overall >= {threshold}, false otherwise>,
  "one_line_verdict": "<single sentence: what the response did well or poorly>",
  "regression_risk": "low" | "medium" | "high",
  "critical_failure": <true if any dimension score is below 0.40, false otherwise>
}}"""

_CONTEXT_SECTION_TEMPLATE = """\
RETRIEVED CONTEXT PROVIDED TO THE AI:
{retrieved_context}
"""

_DIMENSION_WEIGHTS = {
    "instruction_following": 0.40,
    "factual_accuracy": 0.30,
    "format_compliance": 0.20,
    "tone_appropriateness": 0.10,
}


class LLMJudgeAssertion(Assertion):
    """Delegates evaluation to a strong LLM with a structured rubric."""

    def __init__(self, judge_client) -> None:  # type: ignore[annotation-unchecked]
        self._judge = judge_client

    async def evaluate(
        self,
        response: str,
        config: AssertionConfig,
        context: dict,
    ) -> AssertionResult:
        prompt = _build_prompt(response, config, context)
        llm_resp = await self._judge.complete(prompt, system=_JUDGE_SYSTEM_PROMPT, temperature=0.0)

        if not llm_resp.ok:
            return AssertionResult(
                type="llm_judge",
                passed=False,
                score=0.0,
                explanation=f"Judge call failed: {llm_resp.error}",
                weight=config.weight,
            )

        return _parse_judge_response(llm_resp.content, config)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_prompt(response: str, config: AssertionConfig, context: dict) -> str:
    retrieved = context.get("retrieved_context", "")
    context_section = (
        _CONTEXT_SECTION_TEMPLATE.format(retrieved_context=retrieved)
        if retrieved
        else ""
    )
    return _JUDGE_USER_TEMPLATE.format(
        expected_behavior=context.get("expected_behavior", ""),
        original_prompt=context.get("original_prompt", ""),
        actual_response=response,
        context_section=context_section,
        threshold=config.threshold,
    )


def _parse_judge_response(raw: str, config: AssertionConfig) -> AssertionResult:
    """Parse JSON from judge, fall back gracefully on malformed output."""
    try:
        # Strip any accidental markdown fencing
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning("Judge returned unparseable response: %s", e)
        return AssertionResult(
            type="llm_judge",
            passed=False,
            score=0.0,
            explanation=f"Judge response was not valid JSON: {e}",
            weight=config.weight,
        )

    # Recompute weighted overall as safety net (don't trust the model's arithmetic)
    computed_overall = sum(
        data.get(dim, 0.0) * w for dim, w in _DIMENSION_WEIGHTS.items()
    )
    overall = round(computed_overall, 4)
    passed = overall >= config.threshold
    verdict = data.get("one_line_verdict", "No verdict provided")

    return AssertionResult(
        type="llm_judge",
        passed=passed,
        score=overall,
        explanation=(
            f"[{overall:.3f}] {verdict} "
            f"(if={data.get('instruction_following', 0):.2f} "
            f"fa={data.get('factual_accuracy', 0):.2f} "
            f"fc={data.get('format_compliance', 0):.2f} "
            f"ta={data.get('tone_appropriateness', 0):.2f})"
        ),
        weight=config.weight,
    )
